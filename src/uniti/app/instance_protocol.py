"""Strict length-prefixed protocol for forwarding secondary launches."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .platform_policy import normalize_native_path


INSTANCE_PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 256 << 10
MAX_REQUEST_FILES = 128
MAX_PATH_BYTES = 32 << 10
MAX_ERROR_BYTES = 4 << 10
_FRAME_HEADER_BYTES = 4


class InstanceProtocolError(ValueError):
    """Raised when a local-instance message is unsafe or malformed."""


def _text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    if "\0" in value:
        raise ValueError(f"{label} contains a NUL")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8") from exc
    if len(encoded) > maximum:
        raise ValueError(f"{label} exceeds its byte limit")
    return value


def _path(value: object, *, require_absolute: bool) -> str:
    selected = _text(value, "instance path", maximum=MAX_PATH_BYTES)
    if require_absolute and not Path(selected).is_absolute():
        raise ValueError("instance path must be absolute")
    return selected


def _error(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label, maximum=MAX_ERROR_BYTES)


@dataclass(frozen=True, slots=True)
class InstanceRequest:
    version: int
    activate: bool
    files: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != INSTANCE_PROTOCOL_VERSION:
            raise ValueError("instance request version is unsupported")
        if type(self.activate) is not bool:
            raise TypeError("instance request activate flag must be bool")
        if not isinstance(self.files, tuple):
            raise TypeError("instance request files must be a tuple")
        if len(self.files) > MAX_REQUEST_FILES:
            raise ValueError("instance request contains too many files")
        for path in self.files:
            _path(path, require_absolute=False)


@dataclass(frozen=True, slots=True)
class InstancePathOutcome:
    path: str
    opened: bool
    error: str | None

    def __post_init__(self) -> None:
        _path(self.path, require_absolute=True)
        if type(self.opened) is not bool:
            raise TypeError("instance path outcome opened flag must be bool")
        selected_error = _error(self.error, "instance path error")
        if self.opened and selected_error is not None:
            raise ValueError("an opened path cannot also have an error")
        if not self.opened and selected_error is None:
            raise ValueError("a failed path requires a safe error")


@dataclass(frozen=True, slots=True)
class InstanceReply:
    accepted: bool
    outcomes: tuple[InstancePathOutcome, ...]
    error: str | None

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("instance reply accepted flag must be bool")
        if not isinstance(self.outcomes, tuple) or any(
            not isinstance(item, InstancePathOutcome) for item in self.outcomes
        ):
            raise TypeError("instance reply outcomes must be a tuple")
        if len(self.outcomes) > MAX_REQUEST_FILES:
            raise ValueError("instance reply contains too many outcomes")
        selected_error = _error(self.error, "instance reply error")
        if self.accepted and selected_error is not None:
            raise ValueError("an accepted reply cannot also have an error")
        if not self.accepted and selected_error is None:
            raise ValueError("a rejected reply requires a safe error")


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains a duplicate field")
        result[key] = value
    return result


def encode_frame(payload: Mapping[str, object]) -> bytes:
    if not isinstance(payload, Mapping) or any(
        not isinstance(key, str) for key in payload
    ):
        raise InstanceProtocolError("instance payload must be a string-keyed object")
    try:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise InstanceProtocolError("instance payload is not canonical JSON") from exc
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise InstanceProtocolError("instance payload exceeds its byte limit")
    return len(encoded).to_bytes(_FRAME_HEADER_BYTES, "big") + encoded


def decode_frame(frame: bytes) -> dict[str, object]:
    if not isinstance(frame, bytes):
        raise InstanceProtocolError("instance frame must be bytes")
    if len(frame) < _FRAME_HEADER_BYTES:
        raise InstanceProtocolError("instance frame header is incomplete")
    declared = int.from_bytes(frame[:_FRAME_HEADER_BYTES], "big")
    if declared > MAX_MESSAGE_BYTES:
        raise InstanceProtocolError("instance payload exceeds its byte limit")
    if len(frame) != _FRAME_HEADER_BYTES + declared:
        raise InstanceProtocolError("instance frame length does not match its payload")
    payload = frame[_FRAME_HEADER_BYTES:]
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise InstanceProtocolError("instance payload is invalid JSON") from exc
    if not isinstance(value, dict):
        raise InstanceProtocolError("instance payload must be an object")
    return value


def _exact_fields(
    payload: dict[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(payload) != expected:
        raise InstanceProtocolError(f"{label} has missing or unknown fields")


def encode_request(request: InstanceRequest, *, cwd: Path | None = None) -> bytes:
    if not isinstance(request, InstanceRequest):
        raise TypeError("request must be an InstanceRequest")
    try:
        base = (
            normalize_native_path(Path.cwd()).path
            if cwd is None
            else normalize_native_path(".", cwd=cwd).path
        )
    except (TypeError, ValueError) as exc:
        raise InstanceProtocolError("instance working directory is invalid") from exc
    try:
        normalized = tuple(
            str(normalize_native_path(path, cwd=base).path)
            for path in request.files
        )
        for path in normalized:
            _path(path, require_absolute=True)
    except (TypeError, ValueError) as exc:
        raise InstanceProtocolError("instance path cannot be normalized") from exc
    return encode_frame(
        {
            "version": request.version,
            "activate": request.activate,
            "files": list(normalized),
        }
    )


def decode_request(frame: bytes) -> InstanceRequest:
    payload = decode_frame(frame)
    _exact_fields(
        payload,
        frozenset({"version", "activate", "files"}),
        "instance request",
    )
    files = payload["files"]
    if not isinstance(files, list):
        raise InstanceProtocolError("instance request files must be a list")
    try:
        request = InstanceRequest(
            payload["version"],
            payload["activate"],
            tuple(files),
        )
        for path in request.files:
            _path(path, require_absolute=True)
            if str(normalize_native_path(path).path) != path:
                raise ValueError("instance path is not normalized")
    except (TypeError, ValueError) as exc:
        raise InstanceProtocolError("instance request is invalid") from exc
    return request


def encode_reply(reply: InstanceReply) -> bytes:
    if not isinstance(reply, InstanceReply):
        raise TypeError("reply must be an InstanceReply")
    return encode_frame(
        {
            "version": INSTANCE_PROTOCOL_VERSION,
            "accepted": reply.accepted,
            "outcomes": [
                {
                    "path": outcome.path,
                    "opened": outcome.opened,
                    "error": outcome.error,
                }
                for outcome in reply.outcomes
            ],
            "error": reply.error,
        }
    )


def decode_reply(frame: bytes) -> InstanceReply:
    payload = decode_frame(frame)
    _exact_fields(
        payload,
        frozenset({"version", "accepted", "outcomes", "error"}),
        "instance reply",
    )
    if (
        type(payload["version"]) is not int
        or payload["version"] != INSTANCE_PROTOCOL_VERSION
    ):
        raise InstanceProtocolError("instance reply version is unsupported")
    outcomes = payload["outcomes"]
    if not isinstance(outcomes, list) or len(outcomes) > MAX_REQUEST_FILES:
        raise InstanceProtocolError("instance reply outcomes are invalid")
    decoded: list[InstancePathOutcome] = []
    try:
        for item in outcomes:
            if not isinstance(item, dict):
                raise ValueError("instance outcome must be an object")
            _exact_fields(
                item,
                frozenset({"path", "opened", "error"}),
                "instance path outcome",
            )
            decoded.append(
                InstancePathOutcome(item["path"], item["opened"], item["error"])
            )
        reply = InstanceReply(
            payload["accepted"],
            tuple(decoded),
            payload["error"],
        )
    except (TypeError, ValueError) as exc:
        raise InstanceProtocolError("instance reply is invalid") from exc
    return reply


__all__ = [
    "INSTANCE_PROTOCOL_VERSION",
    "MAX_ERROR_BYTES",
    "MAX_MESSAGE_BYTES",
    "MAX_PATH_BYTES",
    "MAX_REQUEST_FILES",
    "InstancePathOutcome",
    "InstanceProtocolError",
    "InstanceReply",
    "InstanceRequest",
    "decode_frame",
    "decode_reply",
    "decode_request",
    "encode_frame",
    "encode_reply",
    "encode_request",
]
