"""Streaming document-save pipeline for UNITI."""

from __future__ import annotations

import codecs
import hashlib
import os
import tempfile
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, Iterator, Literal

from .byte_source import ByteSource
from .decoder import iter_decoded_spans
from .durability import (
    DurabilityAdapter,
    DurabilityError,
    DurabilityLevel,
    DurabilityResult,
    NativeDurabilityAdapter,
)
from .eol import analyze_eol
from .file_identity import ExternalFileChangedError, FileIdentity
from .pieces import EditSegment, PieceTable, SourceSegment
from .offsets import ReadIntent
from .text_format import (
    EOLPolicy,
    EncodingProfile,
    OutputFormat,
    encoding_profiles,
    profile_from_codec,
)

EOLName = Literal["LF", "CRLF", "CR"]
SaveProgress = Callable[[str, int, int | None], None]

_EOL_TEXT: dict[str, str] = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class _TargetMetadata:
    mode: int | None
    xattrs: tuple[tuple[str, bytes], ...]


def _capture_target_metadata(path: Path) -> _TargetMetadata:
    try:
        info = path.stat()
    except FileNotFoundError:
        return _TargetMetadata(None, ())
    mode = stat.S_IMODE(info.st_mode)
    attrs: list[tuple[str, bytes]] = []
    if hasattr(os, "listxattr") and hasattr(os, "getxattr"):
        try:
            names = os.listxattr(path)
        except OSError:
            names = ()
        for name in names:
            try:
                attrs.append((name, os.getxattr(path, name)))
            except OSError:
                continue
    return _TargetMetadata(mode, tuple(attrs))


def _apply_target_metadata(path: Path, metadata: _TargetMetadata) -> None:
    if metadata.mode is not None:
        os.chmod(path, metadata.mode)
    if hasattr(os, "setxattr"):
        for name, value in metadata.xattrs:
            try:
                os.setxattr(path, name, value)
            except OSError:
                # Extended attributes are best-effort across filesystems.
                continue


@dataclass(frozen=True, slots=True)
class SaveOptions:
    encoding: str | None = None
    eol: EOLName | None = None
    chunk_bytes: int = 1 << 20
    chunk_chars: int = 65_536
    output_format: OutputFormat | None = None


@dataclass(frozen=True, slots=True)
class StagedSave:
    destination: Path
    temporary: Path
    output_format: OutputFormat
    byte_length: int
    digest: str
    metadata: _TargetMetadata
    target_identity: FileIdentity | None
    preserves_source_bytes: bool
    _adapter: DurabilityAdapter = field(repr=False, compare=False)
    _verified: bool = False
    _verified_identity: FileIdentity | None = None
    _commit_durability: DurabilityResult | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def verified(self) -> bool:
        return self._verified

    @property
    def commit_durability(self) -> DurabilityResult | None:
        return self._commit_durability


class SaveVerificationError(RuntimeError):
    """Raised when staged bytes do not prove the requested output contract."""


class SaveCancelled(RuntimeError):
    """Raised before commit when a staged save observes cancellation."""


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise SaveCancelled("document save cancelled")


def _durability_error(
    operation: str,
    stage: str,
    error: OSError,
    *,
    file_synced: bool,
) -> DurabilityError:
    return DurabilityError(
        DurabilityResult(
            operation,
            DurabilityLevel.UNSAFE,
            file_synced,
            False,
            False,
            f"{stage}:{type(error).__name__}",
        ),
        error,
    )


def _report(
    progress: SaveProgress | None,
    phase: str,
    completed: int,
    total: int | None,
) -> None:
    if progress is not None:
        progress(phase, completed, total)


class _DigestingWriter:
    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self.byte_length = 0
        self._digest = hashlib.sha256()

    def write(self, payload: bytes) -> int:
        written = self._handle.write(payload)
        if written != len(payload):
            raise OSError("short write while staging document")
        self.byte_length += written
        self._digest.update(payload)
        return written

    @property
    def digest(self) -> str:
        return self._digest.hexdigest()


class UnrepresentableCharacterError(UnicodeError):
    """Raised when strict output encoding cannot represent logical text."""

    def __init__(
        self,
        encoding: str,
        character: str,
        position: int | None = None,
    ) -> None:
        self.encoding = encoding
        self.character = character
        self.position = position
        location = "" if position is None else f" at document character {position}"
        super().__init__(
            f"{encoding} cannot represent U+{ord(character):04X} "
            f"{character!r}{location}"
        )


class UnresolvedMalformedBytesError(UnicodeError):
    """Raised when a transformation would replace preserved source bytes."""

    def __init__(self, position: int, raw: bytes) -> None:
        self.position = position
        self.raw = raw
        super().__init__(
            f"unresolved malformed bytes {raw.hex(' ')} at document character "
            f"{position} block text-format transformation"
        )


class StaleDocumentRevisionError(RuntimeError):
    """Raised when edits make staged output older than the current document."""


def _validate_encodable(text: str, encoding: str, position: int) -> None:
    try:
        text.encode(encoding, errors="strict")
    except UnicodeEncodeError as exc:
        character = exc.object[exc.start : exc.start + 1] or "\ufffd"
        raise UnrepresentableCharacterError(
            encoding,
            character,
            position + exc.start,
        ) from exc


def _preflight_output(
    piece_table: PieceTable,
    *,
    source_profile: EncodingProfile,
    output_format: OutputFormat,
    chunk_chars: int,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    preserves_source_bytes = (
        output_format.encoding == source_profile
        and output_format.eol is EOLPolicy.PRESERVE
    )
    _check_cancelled(cancelled)
    _report(progress, "Checking output", 0, None)
    for chunk in piece_table.iter_annotated_text(chunk_chars=chunk_chars):
        _check_cancelled(cancelled)
        if chunk.invalid_bytes and not preserves_source_bytes:
            first = chunk.invalid_bytes[0]
            raise UnresolvedMalformedBytesError(first.start, first.raw)
        cursor = 0
        for invalid in chunk.invalid_bytes:
            local_start = invalid.start - chunk.document_offset
            local_end = invalid.end - chunk.document_offset
            _validate_encodable(
                chunk.text[cursor:local_start],
                output_format.encoding.codec,
                chunk.document_offset + cursor,
            )
            cursor = local_end
        _validate_encodable(
            chunk.text[cursor:],
            output_format.encoding.codec,
            chunk.document_offset + cursor,
        )
        _report(
            progress,
            "Checking output",
            chunk.document_offset + len(chunk.text),
            None,
        )
    _check_cancelled(cancelled)
    return preserves_source_bytes


def _normalize_encoding(encoding: str) -> str:
    return encoding.lower().replace("_", "-")


def _content_encoding(encoding: str) -> str:
    normalized = _normalize_encoding(encoding)
    if normalized == "utf-8-sig":
        return "utf-8"
    return encoding


def _strict_encode(encoder, text: str, encoding: str, *, final: bool = False) -> bytes:
    try:
        return encoder.encode(text, final=final)
    except UnicodeEncodeError as exc:
        character = exc.object[exc.start : exc.start + 1]
        if not character:
            character = "\ufffd"
        raise UnrepresentableCharacterError(encoding, character) from exc


def _write_preserved_segments(
    handle: BinaryIO,
    source: ByteSource,
    piece_table: PieceTable,
    *,
    encoding: str,
    chunk_bytes: int,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    encoder = codecs.getincrementalencoder(_content_encoding(encoding))(errors="strict")
    completed = 0
    _report(progress, "Writing", 0, None)
    for segment in piece_table.iter_segments():
        _check_cancelled(cancelled)
        if isinstance(segment, SourceSegment):
            for chunk in source.iter_chunks(
                start=segment.byte_start,
                end=segment.byte_end,
                chunk_size=chunk_bytes,
            ):
                _check_cancelled(cancelled)
                handle.write(chunk)
                completed += len(chunk)
                _report(progress, "Writing", completed, None)
        elif isinstance(segment, EditSegment):
            payload = _strict_encode(encoder, segment.text, encoding)
            handle.write(payload)
            completed += len(payload)
            _report(progress, "Writing", completed, None)
    _check_cancelled(cancelled)
    tail = _strict_encode(encoder, "", encoding, final=True)
    if tail:
        handle.write(tail)


def _logical_chunks(piece_table: PieceTable, chunk_chars: int) -> Iterator[str]:
    for _, text in piece_table.iter_text(
        chunk_chars=chunk_chars,
        intent=ReadIntent.STREAMING,
    ):
        yield text


def _normalized_eol_chunks(chunks: Iterator[str], target: str) -> Iterator[str]:
    pending_cr = False
    for text in chunks:
        output: list[str] = []
        for char in text:
            if pending_cr:
                if char == "\n":
                    output.append(target)
                    pending_cr = False
                    continue
                output.append(target)
                pending_cr = False
            if char == "\r":
                pending_cr = True
            elif char == "\n":
                output.append(target)
            else:
                output.append(char)
        if output:
            yield "".join(output)
    if pending_cr:
        yield target


def _write_logical_text(
    handle: BinaryIO,
    piece_table: PieceTable,
    *,
    encoding: str,
    eol: EOLName | None,
    chunk_chars: int,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    encoder = codecs.getincrementalencoder(_content_encoding(encoding))(errors="strict")
    chunks: Iterator[str] = _logical_chunks(piece_table, chunk_chars)
    if eol is not None:
        try:
            target = _EOL_TEXT[eol]
        except KeyError as exc:
            raise ValueError(f"unsupported EOL policy: {eol}") from exc
        chunks = _normalized_eol_chunks(chunks, target)
    completed = 0
    _report(progress, "Writing", 0, None)
    for text in chunks:
        _check_cancelled(cancelled)
        handle.write(_strict_encode(encoder, text, encoding))
        completed += len(text)
        _report(progress, "Writing", completed, None)
    _check_cancelled(cancelled)
    tail = _strict_encode(encoder, "", encoding, final=True)
    if tail:
        handle.write(tail)


def _profile_for_output_encoding(encoding: str) -> EncodingProfile:
    normalized = codecs.lookup(encoding).name
    bom = _UTF8_BOM if normalized == "utf-8-sig" else None
    return profile_from_codec(encoding, bom)


def _output_format_for_options(
    source_profile: EncodingProfile,
    options: SaveOptions,
) -> OutputFormat:
    if options.output_format is not None:
        if options.encoding is not None or options.eol is not None:
            raise ValueError("output_format cannot be combined with encoding or eol")
        return options.output_format
    profile = (
        source_profile
        if options.encoding is None
        else _profile_for_output_encoding(options.encoding)
    )
    policy = EOLPolicy.PRESERVE if options.eol is None else EOLPolicy(options.eol)
    return OutputFormat(profile, policy)


def stage_document(
    source: ByteSource,
    piece_table: PieceTable,
    *,
    source_profile: EncodingProfile,
    destination: str | os.PathLike[str],
    output_format: OutputFormat,
    chunk_bytes: int = 1 << 20,
    chunk_chars: int = 65_536,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
    adapter: DurabilityAdapter | None = None,
) -> StagedSave:
    """Write and fsync a sibling temporary without replacing destination."""

    if chunk_bytes <= 0 or chunk_chars <= 0:
        raise ValueError("save chunk sizes must be positive")
    preserve_bytes = _preflight_output(
        piece_table,
        source_profile=source_profile,
        output_format=output_format,
        chunk_chars=chunk_chars,
        progress=progress,
        cancelled=cancelled,
    )
    target = Path(destination)
    selected_adapter = adapter if adapter is not None else NativeDurabilityAdapter()
    metadata = _capture_target_metadata(target)
    try:
        target_identity = FileIdentity.from_path(target)
    except FileNotFoundError:
        target_identity = None
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".uniti-tmp",
            dir=target.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            writer = _DigestingWriter(handle)
            if output_format.encoding.bom:
                writer.write(output_format.encoding.bom)
            if preserve_bytes:
                _write_preserved_segments(
                    writer,  # type: ignore[arg-type]
                    source,
                    piece_table,
                    encoding=output_format.encoding.codec,
                    chunk_bytes=chunk_bytes,
                    progress=progress,
                    cancelled=cancelled,
                )
            else:
                eol: EOLName | None = None
                if output_format.eol is not EOLPolicy.PRESERVE:
                    eol = output_format.eol.value  # type: ignore[assignment]
                _write_logical_text(
                    writer,  # type: ignore[arg-type]
                    piece_table,
                    encoding=output_format.encoding.codec,
                    eol=eol,
                    chunk_chars=chunk_chars,
                    progress=progress,
                    cancelled=cancelled,
                )
            _check_cancelled(cancelled)
            _apply_target_metadata(temp_path, metadata)
            handle.flush()
            try:
                selected_adapter.sync_file(handle.fileno())
            except OSError as error:
                raise _durability_error(
                    "document_save",
                    "file_sync",
                    error,
                    file_synced=False,
                ) from error
            byte_length = writer.byte_length
            digest = writer.digest
        return StagedSave(
            destination=target,
            temporary=temp_path,
            output_format=output_format,
            byte_length=byte_length,
            digest=digest,
            metadata=metadata,
            target_identity=target_identity,
            preserves_source_bytes=preserve_bytes,
            _adapter=selected_adapter,
        )
    except Exception:
        if fd is not None:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        raise


def _observed_bom(payload: bytes) -> bytes:
    ordered = sorted(encoding_profiles(), key=lambda item: len(item.bom), reverse=True)
    for profile in ordered:
        if profile.bom and payload.startswith(profile.bom):
            return profile.bom
    return b""


def _verify_exact_bom(staged: StagedSave) -> int:
    expected = staged.output_format.encoding.bom
    with staged.temporary.open("rb") as handle:
        prefix = handle.read(4)
    if expected:
        if not prefix.startswith(expected):
            raise SaveVerificationError(
                f"staged BOM does not match {staged.output_format.encoding.label}"
            )
        return len(expected)
    observed = _observed_bom(prefix)
    if observed:
        raise SaveVerificationError(
            f"staged output unexpectedly contains BOM {observed.hex(' ')}"
        )
    return 0


def _file_length_and_digest(
    path: Path,
    *,
    chunk_size: int = 1 << 20,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
    phase: str = "Verifying bytes",
) -> tuple[int, str]:
    length = 0
    digest = hashlib.sha256()
    try:
        total: int | None = path.stat().st_size
    except OSError:
        total = None
    _report(progress, phase, 0, total)
    with path.open("rb") as handle:
        while True:
            _check_cancelled(cancelled)
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            length += len(chunk)
            digest.update(chunk)
            _report(progress, phase, length, total)
    _check_cancelled(cancelled)
    return length, digest.hexdigest()


def _text_chunks(chunks: Iterable[str | tuple[int, str]]) -> Iterator[str]:
    for chunk in chunks:
        if isinstance(chunk, tuple):
            yield chunk[1]
        else:
            yield chunk


def _compare_text_streams(
    expected: Iterator[str],
    actual: Iterator[str],
    *,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    expected_buffer = ""
    actual_buffer = ""
    expected_done = False
    actual_done = False
    position = 0
    _report(progress, "Verifying text", 0, None)
    while True:
        _check_cancelled(cancelled)
        while not expected_buffer and not expected_done:
            try:
                expected_buffer = next(expected)
            except StopIteration:
                expected_done = True
        while not actual_buffer and not actual_done:
            try:
                actual_buffer = next(actual)
            except StopIteration:
                actual_done = True
        if expected_done and actual_done and not expected_buffer and not actual_buffer:
            return
        if expected_done and not expected_buffer:
            raise SaveVerificationError(
                f"staged logical text has unexpected content at character {position}"
            )
        if actual_done and not actual_buffer:
            raise SaveVerificationError(
                f"staged logical text ended at character {position}"
            )
        compared = min(len(expected_buffer), len(actual_buffer))
        if expected_buffer[:compared] != actual_buffer[:compared]:
            mismatch = next(
                index
                for index in range(compared)
                if expected_buffer[index] != actual_buffer[index]
            )
            raise SaveVerificationError(
                f"staged logical text differs at character {position + mismatch}"
            )
        expected_buffer = expected_buffer[compared:]
        actual_buffer = actual_buffer[compared:]
        position += compared
        _report(progress, "Verifying text", position, None)


def _decoded_staged_chunks(staged: StagedSave, content_start: int) -> Iterator[str]:
    with ByteSource.open(staged.temporary) as source:
        for span in iter_decoded_spans(
            source,
            staged.output_format.encoding.codec,
            start=content_start,
            chunk_size=65_536,
        ):
            if span.errors and not staged.preserves_source_bytes:
                first = span.errors[0]
                raise SaveVerificationError(
                    f"staged output does not decode strictly at byte {first.byte_start}"
                )
            yield span.text


def _verify_eol_policy(
    staged: StagedSave,
    *,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    policy = staged.output_format.eol
    if policy is EOLPolicy.PRESERVE:
        return
    with ByteSource.open(staged.temporary) as source:
        report = analyze_eol(
            source,
            encoding=staged.output_format.encoding.codec,
            cancelled=cancelled,
            progress=(
                None
                if progress is None
                else lambda done, total: progress(
                    "Verifying line endings", done, total
                )
            ),
        )
    counts = {
        EOLPolicy.LF: report.lf,
        EOLPolicy.CRLF: report.crlf,
        EOLPolicy.CR: report.cr,
    }
    wrong = sum(count for candidate, count in counts.items() if candidate is not policy)
    if wrong:
        raise SaveVerificationError(
            f"staged line endings do not match requested {policy.value} policy"
        )


def verify_staged_document(
    staged: StagedSave,
    expected_chunks: Iterable[str | tuple[int, str]],
    *,
    progress: SaveProgress | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Reread staged bytes and prove exact byte and logical output invariants."""

    content_start = _verify_exact_bom(staged)
    _check_cancelled(cancelled)
    length, digest = _file_length_and_digest(
        staged.temporary,
        progress=progress,
        cancelled=cancelled,
    )
    if length != staged.byte_length:
        raise SaveVerificationError(
            f"staged byte length changed: expected {staged.byte_length}, found {length}"
        )
    if digest != staged.digest:
        raise SaveVerificationError("staged digest changed after output was written")

    expected: Iterator[str] = _text_chunks(expected_chunks)
    if staged.output_format.eol is not EOLPolicy.PRESERVE:
        expected = _normalized_eol_chunks(
            expected,
            _EOL_TEXT[staged.output_format.eol.value],
        )
    _compare_text_streams(
        expected,
        _decoded_staged_chunks(staged, content_start),
        progress=progress,
        cancelled=cancelled,
    )
    _verify_eol_policy(staged, progress=progress, cancelled=cancelled)
    _check_cancelled(cancelled)
    verified_identity = FileIdentity.from_path(staged.temporary)
    object.__setattr__(staged, "_verified_identity", verified_identity)
    object.__setattr__(staged, "_verified", True)


def commit_staged_document(
    staged: StagedSave,
    *,
    adapter: DurabilityAdapter | None = None,
) -> Path:
    """Atomically replace the destination after successful verification."""

    if not staged._verified or staged._verified_identity is None:
        raise SaveVerificationError("staged output has not been verified")
    try:
        staged_identity = FileIdentity.from_path(staged.temporary)
    except FileNotFoundError as exc:
        raise SaveVerificationError("staged output changed after verification") from exc
    if staged_identity != staged._verified_identity:
        raise SaveVerificationError("staged output changed after verification")
    try:
        target_identity = FileIdentity.from_path(staged.destination)
    except FileNotFoundError:
        target_identity = None
    if target_identity != staged.target_identity:
        raise ExternalFileChangedError(
            staged.destination,
            staged.target_identity,
            target_identity,
        )
    selected_adapter = staged._adapter if adapter is None else adapter
    try:
        selected_adapter.replace(staged.temporary, staged.destination)
    except OSError as error:
        raise _durability_error(
            "document_save",
            "replace",
            error,
            file_synced=True,
        ) from error
    try:
        directory_synced = selected_adapter.sync_directory(
            staged.destination.parent
        ) is True
        reason = None if directory_synced else "directory_sync_unavailable"
    except OSError as error:
        directory_synced = False
        reason = f"directory_sync:{type(error).__name__}"
    result = DurabilityResult(
        "document_save",
        DurabilityLevel.FULL if directory_synced else DurabilityLevel.FILE_SYNCED,
        True,
        True,
        directory_synced,
        reason,
    )
    object.__setattr__(staged, "_commit_durability", result)
    return staged.destination


def discard_staged_document(staged: StagedSave) -> None:
    """Remove an uncommitted sibling temporary when it still exists."""

    try:
        staged.temporary.unlink()
    except FileNotFoundError:
        pass


def save_document(
    source: ByteSource,
    piece_table: PieceTable,
    *,
    source_encoding: str,
    source_bom: bytes | None,
    destination: str | os.PathLike[str],
    options: SaveOptions | None = None,
    before_commit: Callable[[], None] | None = None,
    adapter: DurabilityAdapter | None = None,
) -> Path:
    """Stage, verify, and atomically replace one exact document output."""

    opts = SaveOptions() if options is None else options
    if opts.chunk_bytes <= 0 or opts.chunk_chars <= 0:
        raise ValueError("save chunk sizes must be positive")
    source_profile = profile_from_codec(source_encoding, source_bom)
    output_format = _output_format_for_options(source_profile, opts)
    staged = stage_document(
        source,
        piece_table,
        source_profile=source_profile,
        destination=destination,
        output_format=output_format,
        chunk_bytes=opts.chunk_bytes,
        chunk_chars=opts.chunk_chars,
        adapter=adapter,
    )
    try:
        verify_staged_document(
            staged,
            piece_table.iter_text(
                chunk_chars=opts.chunk_chars,
                intent=ReadIntent.STREAMING,
            ),
        )
        if before_commit is not None:
            before_commit()
        return commit_staged_document(staged)
    finally:
        discard_staged_document(staged)


def atomic_write_text_chunks(
    chunks: Iterator[str],
    destination: str | os.PathLike[str],
    *,
    encoding: str,
    eol: EOLName | None = None,
    bom: bytes | None = None,
    adapter: DurabilityAdapter | None = None,
) -> Path:
    """Strictly encode text chunks through the UNITI atomic-save discipline."""

    target = Path(destination)
    selected_adapter = adapter if adapter is not None else NativeDurabilityAdapter()
    metadata = _capture_target_metadata(target)
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".uniti-tmp",
            dir=target.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            prefix = bom
            if prefix is None and _normalize_encoding(encoding) == "utf-8-sig":
                prefix = _UTF8_BOM
            if prefix:
                handle.write(prefix)
            stream: Iterator[str] = chunks
            if eol is not None:
                try:
                    target_eol = _EOL_TEXT[eol]
                except KeyError as exc:
                    raise ValueError(f"unsupported EOL policy: {eol}") from exc
                stream = _normalized_eol_chunks(stream, target_eol)
            encoder = codecs.getincrementalencoder(_content_encoding(encoding))(errors="strict")
            for text in stream:
                handle.write(_strict_encode(encoder, text, encoding))
            tail = _strict_encode(encoder, "", encoding, final=True)
            if tail:
                handle.write(tail)
            _apply_target_metadata(temp_path, metadata)
            handle.flush()
            try:
                selected_adapter.sync_file(handle.fileno())
            except OSError as error:
                raise _durability_error(
                    "atomic_text_write",
                    "file_sync",
                    error,
                    file_synced=False,
                ) from error
        try:
            selected_adapter.replace(temp_path, target)
        except OSError as error:
            raise _durability_error(
                "atomic_text_write",
                "replace",
                error,
                file_synced=True,
            ) from error
        try:
            selected_adapter.sync_directory(target.parent)
        except OSError:
            pass
        temp_path = None
        return target
    except Exception:
        if fd is not None:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        raise
