"""Progressive source byte-to-character mapping for UNITI."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Hashable

if TYPE_CHECKING:
    from uniti.resources.manager import ResourceManager

from .byte_source import ByteSource
from .decoder import DecodedSpan, decode_span, iter_decoded_spans


@dataclass(frozen=True, slots=True)
class OffsetCheckpoint:
    byte_offset: int
    char_offset: int


class ReadIntent(StrEnum):
    VISIBLE = "visible"
    NEARBY = "nearby"
    RANDOM = "random"
    STREAMING = "streaming"


_BOM_BY_ENCODING: dict[str, bytes] = {
    "utf-8-sig": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}


def _normalize_encoding(encoding: str) -> str:
    return encoding.lower().replace("_", "-")


def _visible_start(source: ByteSource, encoding: str) -> int:
    bom = _BOM_BY_ENCODING.get(_normalize_encoding(encoding))
    if bom is None or source.size < len(bom):
        return 0
    return len(bom) if source.read(0, len(bom)) == bom else 0


class OffsetMapper:
    """Lazily map immutable source byte boundaries to Unicode characters."""

    def __init__(
        self,
        source: ByteSource,
        encoding: str,
        *,
        checkpoint_bytes: int = 65_536,
        resource_manager: "ResourceManager | None" = None,
        cache_owner: Hashable | None = None,
    ) -> None:
        if checkpoint_bytes <= 0:
            raise ValueError("checkpoint_bytes must be positive")
        self._source = source
        self._encoding = encoding
        self._checkpoint_bytes = checkpoint_bytes
        start = _visible_start(source, encoding)
        self._checkpoints: list[OffsetCheckpoint] = [OffsetCheckpoint(start, 0)]
        self._indexed_byte_end = start
        self._indexed_char_end = 0
        self._complete = start >= source.size
        self._span_cache: OrderedDict[tuple[int, int], DecodedSpan] = OrderedDict()
        self._span_cache_limit = 4
        self._resource_manager = resource_manager
        self._cache_owner = cache_owner

    @property
    def indexed_byte_end(self) -> int:
        return self._indexed_byte_end

    @property
    def indexed_char_end(self) -> int:
        return self._indexed_char_end

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def checkpoints(self) -> tuple[OffsetCheckpoint, ...]:
        return tuple(self._checkpoints)

    def publish_progress(
        self,
        checkpoints: tuple[OffsetCheckpoint, ...],
        *,
        complete: bool,
    ) -> bool:
        """Adopt farther immutable-source mapping progress from a snapshot."""

        if not checkpoints:
            raise ValueError("mapping progress must include its initial checkpoint")
        first = checkpoints[0]
        if first != self._checkpoints[0]:
            raise ValueError("mapping progress starts at a different visible source offset")
        previous = first
        for checkpoint in checkpoints[1:]:
            if (
                checkpoint.byte_offset <= previous.byte_offset
                or checkpoint.char_offset <= previous.char_offset
                or checkpoint.byte_offset > self._source.size
            ):
                raise ValueError("mapping progress checkpoints must be monotonic")
            previous = checkpoint
        final = checkpoints[-1]
        if complete and final.byte_offset != self._source.size:
            raise ValueError("complete mapping progress must reach source EOF")
        if final.byte_offset < self._indexed_byte_end:
            return False
        if (
            final.byte_offset == self._indexed_byte_end
            and final.char_offset < self._indexed_char_end
        ):
            return False
        self._checkpoints = list(checkpoints)
        self._indexed_byte_end = final.byte_offset
        self._indexed_char_end = final.char_offset
        self._complete = bool(complete)
        self._span_cache.clear()
        return True

    def publish_decoded_span(self, span: DecodedSpan) -> None:
        """Advance mapping from a span already decoded by a streaming reader."""

        if span.byte_start != self._indexed_byte_end:
            raise ValueError("decoded span does not continue current mapping progress")
        self._indexed_byte_end = span.byte_end
        self._indexed_char_end += len(span.text)
        checkpoint = OffsetCheckpoint(
            self._indexed_byte_end,
            self._indexed_char_end,
        )
        if checkpoint != self._checkpoints[-1]:
            self._checkpoints.append(checkpoint)
        self._complete = self._indexed_byte_end >= self._source.size

    def _advance(self, intent: ReadIntent = ReadIntent.RANDOM) -> None:
        if self._complete:
            return
        iterator = iter_decoded_spans(
            self._source,
            self._encoding,
            start=self._indexed_byte_end,
            end=self._source.size,
            chunk_size=self._checkpoint_bytes,
        )
        try:
            span = next(iterator)
        except StopIteration:
            self._complete = True
            return

        if intent is not ReadIntent.STREAMING:
            self._cache_span(span)
        self._indexed_byte_end = span.byte_end
        self._indexed_char_end += len(span.text)
        checkpoint = OffsetCheckpoint(self._indexed_byte_end, self._indexed_char_end)
        if checkpoint != self._checkpoints[-1]:
            self._checkpoints.append(checkpoint)
        self._complete = self._indexed_byte_end >= self._source.size

    @staticmethod
    def _span_size(span: DecodedSpan) -> int:
        return span.retained_size_bytes

    def _cache_span(self, span: DecodedSpan) -> None:
        key = (span.byte_start, span.byte_end)
        if self._resource_manager is not None and self._cache_owner is not None:
            from uniti.resources.cache import CachePriority

            self._resource_manager.put_cache(
                self._cache_owner,
                ("offset-span",) + key,
                span,
                size_bytes=self._span_size(span),
                priority=CachePriority.INDEX,
            )
            return
        self._span_cache[key] = span
        self._span_cache.move_to_end(key)
        while len(self._span_cache) > self._span_cache_limit:
            self._span_cache.popitem(last=False)

    def _decoded_interval(
        self,
        index: int,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> DecodedSpan:
        checkpoint = self._checkpoints[index]
        if index + 1 >= len(self._checkpoints):
            raise ValueError("mapping interval is not indexed")
        end_checkpoint = self._checkpoints[index + 1]
        key = (checkpoint.byte_offset, end_checkpoint.byte_offset)
        if (
            intent is not ReadIntent.STREAMING
            and self._resource_manager is not None
            and self._cache_owner is not None
        ):
            cached = self._resource_manager.get_cache(
                self._cache_owner, ("offset-span",) + key
            )
            if cached is not None:
                return cached
        elif intent is not ReadIntent.STREAMING:
            cached = self._span_cache.get(key)
            if cached is not None:
                self._span_cache.move_to_end(key)
                return cached
        span = decode_span(
            self._source,
            checkpoint.byte_offset,
            end_checkpoint.byte_offset - checkpoint.byte_offset,
            self._encoding,
        )
        if intent is not ReadIntent.STREAMING:
            self._cache_span(span)
        return span

    def _ensure_char(
        self,
        char_offset: int,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        while char_offset > self._indexed_char_end and not self._complete:
            self._advance(intent)
        if char_offset > self._indexed_char_end:
            raise ValueError("character offset is beyond end of source")

    def _ensure_byte(
        self,
        byte_offset: int,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> None:
        visible_start = self._checkpoints[0].byte_offset
        if byte_offset < visible_start or byte_offset > self._source.size:
            raise ValueError("byte offset is outside visible source text")
        while byte_offset > self._indexed_byte_end and not self._complete:
            self._advance(intent)
        if byte_offset > self._indexed_byte_end:
            raise ValueError("byte offset is beyond indexed source")

    def char_to_byte(
        self,
        char_offset: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> int:
        self._ensure_char(char_offset, intent)
        char_points = [cp.char_offset for cp in self._checkpoints]
        index = bisect_right(char_points, char_offset) - 1
        checkpoint = self._checkpoints[index]
        if checkpoint.char_offset == char_offset:
            return checkpoint.byte_offset

        if index + 1 >= len(self._checkpoints):
            raise ValueError("character offset is beyond end of source")
        span = self._decoded_interval(index, intent)
        local = char_offset - checkpoint.char_offset
        return span.byte_offset_for_char_boundary(local)

    def byte_to_char(
        self,
        byte_offset: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> int:
        self._ensure_byte(byte_offset, intent)
        byte_points = [cp.byte_offset for cp in self._checkpoints]
        index = bisect_right(byte_points, byte_offset) - 1
        checkpoint = self._checkpoints[index]
        if checkpoint.byte_offset == byte_offset:
            return checkpoint.char_offset

        if index + 1 >= len(self._checkpoints):
            raise ValueError("byte offset is not a visible character boundary")
        span = self._decoded_interval(index, intent)
        local_byte_offset = byte_offset - checkpoint.byte_offset
        boundary_index = bisect_left(span.char_boundaries, local_byte_offset)
        if (
            boundary_index >= len(span.char_boundaries)
            or span.char_boundaries[boundary_index] != local_byte_offset
        ):
            raise ValueError("byte offset is not a visible character boundary")
        return checkpoint.char_offset + boundary_index

    def total_chars(self, *, intent: ReadIntent = ReadIntent.RANDOM) -> int:
        while not self._complete:
            self._advance(intent)
        return self._indexed_char_end
