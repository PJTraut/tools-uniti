from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from uniti.app.instance_protocol import (
    INSTANCE_PROTOCOL_VERSION,
    MAX_MESSAGE_BYTES,
    MAX_PATH_BYTES,
    MAX_REQUEST_FILES,
    InstancePathOutcome,
    InstanceProtocolError,
    InstanceReply,
    InstanceRequest,
    decode_frame,
    decode_reply,
    decode_request,
    encode_frame,
    encode_reply,
    encode_request,
)


def _raw_frame(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + payload


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x00\x00\x00\x02{}trailing",
        (MAX_MESSAGE_BYTES + 1).to_bytes(4, "big") + b"{}",
        _raw_frame(b"\xff"),
        encode_frame({"version": 2, "activate": True, "files": []}),
        encode_frame({"version": True, "activate": True, "files": []}),
        encode_frame({"version": 1, "activate": "yes", "files": []}),
        encode_frame(
            {"version": 1, "activate": True, "files": ["/x"] * 129}
        ),
        encode_frame(
            {
                "version": 1,
                "activate": True,
                "files": ["/" + "x" * (MAX_PATH_BYTES + 1)],
            }
        ),
        encode_frame({"version": 1, "activate": True, "files": ["/a\0b"]}),
        encode_frame({"version": 1, "activate": True, "files": ["relative"]}),
        encode_frame(
            {"version": 1, "activate": True, "files": [], "command": "unknown"}
        ),
    ],
)
def test_instance_protocol_rejects_malformed_or_oversized_frames(payload):
    with pytest.raises(InstanceProtocolError):
        decode_request(payload)


def test_instance_protocol_rejects_excessive_json_nesting_without_recursing():
    nested = b"[" * 10_000 + b"]" * 10_000

    with pytest.raises(InstanceProtocolError):
        decode_request(_raw_frame(nested))


def test_encode_request_normalizes_relative_paths_once_and_preserves_order(
    tmp_path: Path,
):
    request = InstanceRequest(
        INSTANCE_PROTOCOL_VERSION,
        True,
        ("second.txt", "folder/../first.txt"),
    )

    decoded = decode_request(encode_request(request, cwd=tmp_path))

    assert decoded.files == (
        str((tmp_path / "second.txt").resolve()),
        str((tmp_path / "first.txt").resolve()),
    )
    assert decoded.activate is True


def test_request_decoder_rejects_absolute_but_unnormalized_paths(tmp_path: Path):
    unnormalized = str(tmp_path / "folder" / ".." / "document.txt")
    frame = encode_frame(
        {"version": 1, "activate": True, "files": [unnormalized]}
    )

    with pytest.raises(InstanceProtocolError):
        decode_request(frame)


def test_request_frame_is_canonical_json_with_one_exact_length_prefix(tmp_path: Path):
    path = str((tmp_path / "document.txt").resolve())
    frame = encode_request(InstanceRequest(1, False, (path,)))

    assert int.from_bytes(frame[:4], "big") == len(frame[4:])
    assert frame[4:] == (
        json.dumps(
            {"activate": False, "files": [path], "version": 1},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert decode_frame(frame) == {
        "activate": False,
        "files": [path],
        "version": 1,
    }


def test_reply_round_trip_preserves_bounded_per_path_outcomes(tmp_path: Path):
    first = str((tmp_path / "first.txt").resolve())
    second = str((tmp_path / "second.txt").resolve())
    reply = InstanceReply(
        accepted=True,
        outcomes=(
            InstancePathOutcome(first, True, None),
            InstancePathOutcome(second, False, "Open failed safely."),
        ),
        error=None,
    )

    assert decode_reply(encode_reply(reply)) == reply


def test_reply_decoder_rejects_unbounded_outcomes_and_unknown_fields(tmp_path: Path):
    path = str((tmp_path / "x").resolve())
    too_many = encode_frame(
        {
            "version": 1,
            "accepted": True,
            "outcomes": [
                {"path": path, "opened": True, "error": None}
                for _index in range(MAX_REQUEST_FILES + 1)
            ],
            "error": None,
        }
    )
    unknown = encode_frame(
        {
            "version": 1,
            "accepted": True,
            "outcomes": [],
            "error": None,
            "contents": "private document contents",
        }
    )

    with pytest.raises(InstanceProtocolError):
        decode_reply(too_many)
    with pytest.raises(InstanceProtocolError):
        decode_reply(unknown)


def test_protocol_records_are_immutable(tmp_path: Path):
    request = InstanceRequest(1, True, (str(tmp_path.resolve()),))

    with pytest.raises(FrozenInstanceError):
        request.activate = False
