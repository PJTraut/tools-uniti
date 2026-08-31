"""Streaming document-save pipeline for UNITI."""

from __future__ import annotations

import codecs
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Literal

from .byte_source import ByteSource
from .pieces import EditSegment, PieceTable, SourceSegment

EOLName = Literal["LF", "CRLF", "CR"]

_EOL_TEXT: dict[str, str] = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class SaveOptions:
    encoding: str | None = None
    eol: EOLName | None = None
    chunk_bytes: int = 1 << 20
    chunk_chars: int = 65_536


class UnrepresentableCharacterError(UnicodeError):
    """Raised when strict output encoding cannot represent logical text."""

    def __init__(self, encoding: str, character: str) -> None:
        self.encoding = encoding
        self.character = character
        super().__init__(
            f"{encoding} cannot represent U+{ord(character):04X} {character!r}"
        )


def _normalize_encoding(encoding: str) -> str:
    return encoding.lower().replace("_", "-")


def _content_encoding(encoding: str) -> str:
    normalized = _normalize_encoding(encoding)
    if normalized == "utf-8-sig":
        return "utf-8"
    return encoding


def _output_prefix(
    source_encoding: str,
    source_bom: bytes | None,
    output_encoding: str,
) -> bytes:
    output_norm = _normalize_encoding(output_encoding)
    source_norm = _normalize_encoding(source_encoding)
    if output_norm == "utf-8-sig":
        return _UTF8_BOM
    if output_norm == source_norm and source_bom is not None:
        return source_bom
    return b""


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
) -> None:
    encoder = codecs.getincrementalencoder(_content_encoding(encoding))(errors="strict")
    for segment in piece_table.iter_segments():
        if isinstance(segment, SourceSegment):
            for chunk in source.iter_chunks(
                start=segment.byte_start,
                end=segment.byte_end,
                chunk_size=chunk_bytes,
            ):
                handle.write(chunk)
        elif isinstance(segment, EditSegment):
            handle.write(_strict_encode(encoder, segment.text, encoding))
    tail = _strict_encode(encoder, "", encoding, final=True)
    if tail:
        handle.write(tail)


def _logical_chunks(piece_table: PieceTable, chunk_chars: int) -> Iterator[str]:
    for _, text in piece_table.iter_text(chunk_chars=chunk_chars):
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
) -> None:
    encoder = codecs.getincrementalencoder(_content_encoding(encoding))(errors="strict")
    chunks: Iterator[str] = _logical_chunks(piece_table, chunk_chars)
    if eol is not None:
        try:
            target = _EOL_TEXT[eol]
        except KeyError as exc:
            raise ValueError(f"unsupported EOL policy: {eol}") from exc
        chunks = _normalized_eol_chunks(chunks, target)
    for text in chunks:
        handle.write(_strict_encode(encoder, text, encoding))
    tail = _strict_encode(encoder, "", encoding, final=True)
    if tail:
        handle.write(tail)


def save_document(
    source: ByteSource,
    piece_table: PieceTable,
    *,
    source_encoding: str,
    source_bom: bytes | None,
    destination: str | os.PathLike[str],
    options: SaveOptions | None = None,
) -> Path:
    """Stream the logical document to a temporary file and atomically replace target."""

    opts = SaveOptions() if options is None else options
    if opts.chunk_bytes <= 0 or opts.chunk_chars <= 0:
        raise ValueError("save chunk sizes must be positive")
    output_encoding = opts.encoding or source_encoding
    target = Path(destination)
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
            prefix = _output_prefix(source_encoding, source_bom, output_encoding)
            if prefix:
                handle.write(prefix)
            preserve_bytes = (
                _normalize_encoding(output_encoding) == _normalize_encoding(source_encoding)
                and opts.eol is None
            )
            if preserve_bytes:
                _write_preserved_segments(
                    handle,
                    source,
                    piece_table,
                    encoding=output_encoding,
                    chunk_bytes=opts.chunk_bytes,
                )
            else:
                _write_logical_text(
                    handle,
                    piece_table,
                    encoding=output_encoding,
                    eol=opts.eol,
                    chunk_chars=opts.chunk_chars,
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
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


def atomic_write_text_chunks(
    chunks: Iterator[str],
    destination: str | os.PathLike[str],
    *,
    encoding: str,
    eol: EOLName | None = None,
    bom: bytes | None = None,
) -> Path:
    """Strictly encode text chunks through the UNITI atomic-save discipline."""

    target = Path(destination)
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
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
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
