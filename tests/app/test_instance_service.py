from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from uniti.app.instance_protocol import (
    InstancePathOutcome,
    InstanceReply,
    InstanceRequest,
    decode_request,
    encode_reply,
)
from uniti.app.instance_service import (
    InstanceRole,
    InstanceService,
    InstanceServiceError,
    InstanceStart,
    InstanceTimeoutError,
    InstanceUnavailableError,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _endpoint() -> str:
    return f"uniti-test-{uuid.uuid4().hex}"


def _pump(app: QCoreApplication, predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    app.processEvents()
    return bool(predicate())


def _accepted_reply(request: InstanceRequest) -> InstanceReply:
    return InstanceReply(
        True,
        tuple(InstancePathOutcome(path, True, None) for path in request.files),
        None,
    )


def test_primary_receives_one_normalized_request_and_secondary_is_forwarded(
    qapp,
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    first = str(
        (tmp_path / "Unicode Ω & spaced" / "first Привет.txt").resolve()
    )
    second = str(
        (tmp_path / "Unicode Ω & spaced" / "second file.txt").resolve()
    )
    primary = InstanceService(lock_path, endpoint)
    secondary = InstanceService(lock_path, endpoint)
    received: list[InstanceRequest] = []

    def handle(connection, request: InstanceRequest) -> None:
        received.append(request)
        primary.reply(connection, _accepted_reply(request))

    primary.requestReceived.connect(handle)
    try:
        started = primary.start(InstanceRequest(1, True, ()))
        forwarded = secondary.start(
            InstanceRequest(1, True, (first, second)),
        )

        assert started.role is InstanceRole.PRIMARY
        assert forwarded.role is InstanceRole.FORWARDED
        assert forwarded.reply == InstanceReply(
            True,
            (
                InstancePathOutcome(first, True, None),
                InstancePathOutcome(second, True, None),
            ),
            None,
        )
        assert received == [InstanceRequest(1, True, (first, second))]
        assert primary.is_listening is True
        assert secondary.is_listening is False
    finally:
        secondary.close()
        primary.close()


def test_accepted_reply_requires_one_ordered_outcome_per_requested_path(
    qapp,
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    requested = str((tmp_path / "requested.txt").resolve())
    primary = InstanceService(lock_path, endpoint)
    secondary = InstanceService(lock_path, endpoint)
    reply_errors: list[Exception] = []

    def handle(connection, _request: InstanceRequest) -> None:
        try:
            primary.reply(connection, InstanceReply(True, (), None))
        except Exception as error:
            reply_errors.append(error)
            connection.abort()

    primary.requestReceived.connect(handle)
    try:
        primary.start(InstanceRequest(1, True, ()))

        with pytest.raises(InstanceServiceError, match="closed before replying"):
            secondary.start(InstanceRequest(1, True, (requested,)))

        assert len(reply_errors) == 1
        assert isinstance(reply_errors[0], InstanceServiceError)
        assert "one ordered outcome" in str(reply_errors[0])
    finally:
        secondary.close()
        primary.close()


def test_activation_only_request_is_forwarded_without_creating_another_server(
    qapp,
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    primary = InstanceService(lock_path, endpoint)
    secondary = InstanceService(lock_path, endpoint)
    requests: list[InstanceRequest] = []

    def handle(connection, request: InstanceRequest) -> None:
        requests.append(request)
        primary.reply(connection, _accepted_reply(request))

    primary.requestReceived.connect(handle)
    try:
        assert primary.start(InstanceRequest(1, True, ())).role is InstanceRole.PRIMARY
        result = secondary.start(InstanceRequest(1, True, ()))

        assert result.role is InstanceRole.FORWARDED
        assert result.reply == InstanceReply(True, (), None)
        assert requests == [InstanceRequest(1, True, ())]
    finally:
        secondary.close()
        primary.close()


def test_live_lease_with_unreachable_endpoint_never_takes_over(qapp, tmp_path: Path):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    owner = QLockFile(str(lock_path))
    assert owner.tryLock(0)
    contender = InstanceService(lock_path, endpoint)
    try:
        with pytest.raises(InstanceUnavailableError, match="already running"):
            contender.start(InstanceRequest(1, True, ()), timeout_ms=60)

        assert owner.isLocked() is True
        assert contender.is_listening is False
    finally:
        contender.close()
        owner.unlock()


def test_secondary_retries_during_the_lease_to_endpoint_startup_gap(
    qapp,
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    owner = QLockFile(str(lock_path))
    server = QLocalServer()
    sockets: list[QLocalSocket] = []
    buffers: dict[QLocalSocket, bytearray] = {}
    assert owner.tryLock(0)

    def accept() -> None:
        connection = server.nextPendingConnection()
        assert connection is not None
        sockets.append(connection)
        buffers[connection] = bytearray()

        def respond() -> None:
            buffer = buffers[connection]
            buffer.extend(bytes(connection.readAll()))
            if len(buffer) < 4:
                return
            expected = 4 + int.from_bytes(buffer[:4], "big")
            if len(buffer) < expected:
                return
            request = decode_request(bytes(buffer))
            connection.write(encode_reply(_accepted_reply(request)))
            connection.flush()
            connection.disconnectFromServer()

        connection.readyRead.connect(respond)
        if connection.bytesAvailable():
            respond()

    server.newConnection.connect(accept)
    QTimer.singleShot(40, lambda: server.listen(endpoint))
    contender = InstanceService(lock_path, endpoint)
    try:
        result = contender.start(InstanceRequest(1, True, ()), timeout_ms=500)

        assert result == InstanceStart(
            InstanceRole.FORWARDED,
            InstanceReply(True, (), None),
        )
        assert owner.isLocked() is True
        assert contender.is_listening is False
    finally:
        contender.close()
        for connection in sockets:
            connection.abort()
        server.close()
        QLocalServer.removeServer(endpoint)
        owner.unlock()


def test_connected_owner_that_does_not_reply_times_out_without_takeover(
    qapp,
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    owner = QLockFile(str(lock_path))
    server = QLocalServer()
    assert owner.tryLock(0)
    assert server.listen(endpoint)
    contender = InstanceService(lock_path, endpoint)
    try:
        with pytest.raises(InstanceTimeoutError, match="timed out"):
            contender.start(InstanceRequest(1, True, ()), timeout_ms=80)

        assert owner.isLocked() is True
        assert contender.is_listening is False
    finally:
        contender.close()
        server.close()
        QLocalServer.removeServer(endpoint)
        owner.unlock()


def test_primary_rejects_malformed_socket_input_before_emitting_request(
    qapp,
    tmp_path: Path,
):
    endpoint = _endpoint()
    primary = InstanceService(tmp_path / "instance.lock", endpoint)
    received: list[InstanceRequest] = []
    primary.requestReceived.connect(lambda _connection, request: received.append(request))
    peer = QLocalSocket()
    try:
        primary.start(InstanceRequest(1, True, ()))
        peer.connectToServer(endpoint)
        assert peer.waitForConnected(1000)
        peer.write(b"\x00\x00\x00\x02{}trailing")
        peer.flush()

        assert _pump(
            qapp,
            lambda: peer.state() == QLocalSocket.LocalSocketState.UnconnectedState,
        )
        assert received == []
    finally:
        peer.abort()
        primary.close()


@pytest.mark.skipif(
    sys.platform == "darwin" or sys.platform.startswith("win"),
    reason="requires a filesystem-backed QLocalServer endpoint",
)
def test_primary_removes_stale_endpoint_only_after_acquiring_lease(
    qapp,
    tmp_path: Path,
):
    endpoint = _endpoint()
    probe = QLocalServer()
    assert probe.listen(endpoint)
    socket_path = Path(probe.fullServerName())
    probe.close()
    assert socket_path.is_absolute()
    socket_path.write_bytes(b"stale endpoint")
    service = InstanceService(tmp_path / "instance.lock", endpoint)
    try:
        result = service.start(InstanceRequest(1, True, ()))

        assert result.role is InstanceRole.PRIMARY
        assert service.is_listening is True
        assert stat.S_ISSOCK(socket_path.stat().st_mode)
    finally:
        service.close()


def test_dead_lock_owner_is_recovered_by_qt_stale_lock_semantics(qapp, tmp_path: Path):
    lock_path = tmp_path / "instance.lock"
    script = (
        "import os, sys\n"
        "from PySide6.QtCore import QLockFile\n"
        "lock = QLockFile(sys.argv[1])\n"
        "assert lock.tryLock(0)\n"
        "os._exit(0)\n"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(lock_path)],
        check=True,
        cwd=Path.cwd(),
    )
    assert lock_path.exists()
    service = InstanceService(lock_path, _endpoint())
    try:
        result = service.start(InstanceRequest(1, True, ()), timeout_ms=500)

        assert result.role is InstanceRole.PRIMARY
        assert service.is_listening is True
    finally:
        service.close()


def test_two_simultaneous_processes_forward_unicode_path_to_one_primary(
    tmp_path: Path,
):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    first_result = tmp_path / "first.json"
    second_result = tmp_path / "second.json"
    source = tmp_path / "Unicode Ω & spaced" / "leading- Привет & file.txt"
    source.parent.mkdir()
    source.write_text("content is not IPC evidence", encoding="utf-8")
    script = r'''import json, sys, time
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from uniti.app.instance_protocol import InstancePathOutcome, InstanceReply, InstanceRequest
from uniti.app.instance_service import InstanceService

app = QCoreApplication([])
lock_path, endpoint, output, other, source = sys.argv[1:]
service = InstanceService(Path(lock_path), endpoint)
service.requestReceived.connect(
    lambda connection, request: service.reply(
        connection,
        InstanceReply(
            True,
            tuple(InstancePathOutcome(path, True, None) for path in request.files),
            None,
        ),
    )
)
try:
    started = service.start(InstanceRequest(1, True, (source,)), timeout_ms=3000)
    Path(output).write_text(
        json.dumps(
            {
                "role": started.role.value,
                "accepted": started.reply is None or started.reply.accepted,
                "outcomes": 0 if started.reply is None else len(started.reply.outcomes),
            }
        ),
        encoding="utf-8",
    )
    if started.role.value == "primary":
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not Path(other).exists():
            app.processEvents()
            time.sleep(0.002)
finally:
    service.close()
'''
    first = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(lock_path),
            endpoint,
            str(first_result),
            str(second_result),
            str(source),
        ],
        cwd=Path.cwd(),
    )
    second = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(lock_path),
            endpoint,
            str(second_result),
            str(first_result),
            str(source),
        ],
        cwd=Path.cwd(),
    )
    try:
        assert first.wait(timeout=8) == 0
        assert second.wait(timeout=8) == 0
    finally:
        for process in (first, second):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)

    results = (
        json.loads(first_result.read_text(encoding="utf-8")),
        json.loads(second_result.read_text(encoding="utf-8")),
    )
    roles = {result["role"] for result in results}
    assert roles == {"primary", "forwarded"}
    forwarded = next(result for result in results if result["role"] == "forwarded")
    assert forwarded == {"role": "forwarded", "accepted": True, "outcomes": 1}


def test_close_releases_endpoint_and_lease_for_the_next_primary(qapp, tmp_path: Path):
    lock_path = tmp_path / "instance.lock"
    endpoint = _endpoint()
    first = InstanceService(lock_path, endpoint)
    second = InstanceService(lock_path, endpoint)

    assert first.start(InstanceRequest(1, True, ())).role is InstanceRole.PRIMARY
    first.close()

    try:
        assert second.start(InstanceRequest(1, True, ())).role is InstanceRole.PRIMARY
    finally:
        second.close()


def test_start_rejects_non_positive_timeouts(tmp_path: Path):
    service = InstanceService(tmp_path / "instance.lock", _endpoint())
    try:
        with pytest.raises(ValueError, match="timeout"):
            service.start(InstanceRequest(1, True, ()), timeout_ms=0)
    finally:
        service.close()
