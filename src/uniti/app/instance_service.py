"""One user-scoped UNITI lease with bounded local request forwarding."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .instance_protocol import (
    MAX_MESSAGE_BYTES,
    InstanceProtocolError,
    InstanceReply,
    InstanceRequest,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
)


_FRAME_HEADER_BYTES = 4
_MAX_FRAME_BYTES = _FRAME_HEADER_BYTES + MAX_MESSAGE_BYTES


class InstanceServiceError(RuntimeError):
    """Base error for local instance arbitration and transport."""


class InstanceUnavailableError(InstanceServiceError):
    """Raised when a live owner cannot be reached safely."""


class InstanceTimeoutError(InstanceServiceError):
    """Raised when a local owner does not answer within the bound."""


class InstanceRole(StrEnum):
    PRIMARY = "primary"
    FORWARDED = "forwarded"


@dataclass(frozen=True, slots=True)
class InstanceStart:
    role: InstanceRole
    reply: InstanceReply | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, InstanceRole):
            raise TypeError("instance start role must be an InstanceRole")
        if self.role is InstanceRole.PRIMARY and self.reply is not None:
            raise ValueError("a primary start cannot contain a forwarded reply")
        if self.role is InstanceRole.FORWARDED and not isinstance(
            self.reply, InstanceReply
        ):
            raise ValueError("a forwarded start requires an InstanceReply")


@dataclass(slots=True)
class _Peer:
    buffer: bytearray
    expected_bytes: int | None
    timer: QTimer
    request: InstanceRequest | None = None
    emitted: bool = False
    replied: bool = False


class _EndpointUnavailable(RuntimeError):
    pass


class InstanceService(QObject):
    """Own the one-writer lease or forward a bounded launch request."""

    requestReceived = Signal(object, object)

    def __init__(
        self,
        lock_path: str | Path,
        endpoint_name: str,
        parent=None,
        *,
        stale_lock_time_ms: int = 30_000,
        request_timeout_ms: int = 3_000,
    ) -> None:
        super().__init__(parent)
        selected_lock = Path(lock_path)
        if not str(selected_lock):
            raise ValueError("instance lock path must be nonempty")
        if (
            not isinstance(endpoint_name, str)
            or not endpoint_name
            or "\0" in endpoint_name
            or len(endpoint_name.encode("utf-8")) > 200
        ):
            raise ValueError("instance endpoint name is invalid")
        for value, label in (
            (stale_lock_time_ms, "stale lock time"),
            (request_timeout_ms, "request timeout"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if request_timeout_ms == 0:
            raise ValueError("request timeout must be positive")

        selected_lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_path = selected_lock.resolve(strict=False)
        self.endpoint_name = endpoint_name
        self._lock = QLockFile(str(self.lock_path))
        self._lock.setStaleLockTime(stale_lock_time_ms)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)
        self._request_timeout_ms = request_timeout_ms
        self._peers: dict[QLocalSocket, _Peer] = {}
        self._owns_lease = False
        self._started = False
        self._closed = False
        self._role: InstanceRole | None = None

    @property
    def role(self) -> InstanceRole | None:
        return self._role

    @property
    def is_listening(self) -> bool:
        return self._server.isListening()

    @staticmethod
    def _validate_timeout(timeout_ms: int) -> int:
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("instance timeout must be a positive integer")
        return timeout_ms

    def _become_primary(self) -> InstanceStart:
        if not self._lock.isLocked():
            raise InstanceServiceError("instance lease was not acquired")
        self._owns_lease = True
        QLocalServer.removeServer(self.endpoint_name)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self.endpoint_name):
            detail = self._server.errorString()
            self._owns_lease = False
            self._lock.unlock()
            raise InstanceServiceError(
                f"could not open the local UNITI endpoint ({detail})"
            )
        self._started = True
        self._role = InstanceRole.PRIMARY
        return InstanceStart(InstanceRole.PRIMARY)

    def start(
        self,
        request: InstanceRequest,
        *,
        timeout_ms: int = 3_000,
    ) -> InstanceStart:
        if self._closed:
            raise InstanceServiceError("instance service is closed")
        if self._started:
            raise InstanceServiceError("instance service is already started")
        if not isinstance(request, InstanceRequest):
            raise TypeError("request must be an InstanceRequest")
        selected_timeout = self._validate_timeout(timeout_ms)
        if self._lock.tryLock(0):
            return self._become_primary()
        if self._lock.error() != QLockFile.LockError.LockFailedError:
            raise InstanceServiceError("UNITI instance lease cannot be accessed")

        deadline = time.monotonic() + selected_timeout / 1000
        while True:
            remaining = self._remaining_ms(deadline)
            if remaining <= 0:
                raise InstanceUnavailableError(
                    "UNITI is already running but its local endpoint is unreachable"
                )
            try:
                reply = self._forward(request, remaining)
                break
            except _EndpointUnavailable as exc:
                if self._lock.tryLock(0):
                    return self._become_primary()
                if self._remaining_ms(deadline) <= 0:
                    raise InstanceUnavailableError(
                        "UNITI is already running but its local endpoint is unreachable"
                    ) from exc
                self._process_events()
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        self._started = True
        self._role = InstanceRole.FORWARDED
        return InstanceStart(InstanceRole.FORWARDED, reply)

    @staticmethod
    def _remaining_ms(deadline: float) -> int:
        return max(0, math.ceil((deadline - time.monotonic()) * 1000))

    @staticmethod
    def _process_events() -> None:
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()

    def _connect_secondary(self, socket: QLocalSocket, deadline: float) -> None:
        socket.connectToServer(self.endpoint_name)
        while socket.state() == QLocalSocket.LocalSocketState.ConnectingState:
            remaining = self._remaining_ms(deadline)
            if remaining <= 0:
                socket.abort()
                raise _EndpointUnavailable("local endpoint connection timed out")
            socket.waitForConnected(min(remaining, 20))
            self._process_events()
        if socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
            socket.abort()
            raise _EndpointUnavailable(socket.errorString())

    def _write_secondary(
        self,
        socket: QLocalSocket,
        frame: bytes,
        deadline: float,
    ) -> None:
        if socket.write(frame) != len(frame):
            socket.abort()
            raise InstanceServiceError("could not queue the local UNITI request")
        socket.flush()
        while socket.bytesToWrite() > 0:
            remaining = self._remaining_ms(deadline)
            if remaining <= 0 or not socket.waitForBytesWritten(min(remaining, 20)):
                self._process_events()
                if self._remaining_ms(deadline) <= 0:
                    socket.abort()
                    raise InstanceTimeoutError("UNITI request timed out while sending")

    def _read_secondary(self, socket: QLocalSocket, deadline: float) -> bytes:
        buffer = bytearray()
        expected: int | None = None
        while True:
            self._process_events()
            available = socket.bytesAvailable()
            if available > 0:
                allowance = _MAX_FRAME_BYTES + 1 - len(buffer)
                if allowance <= 0:
                    socket.abort()
                    raise InstanceServiceError("UNITI reply exceeds its safe limit")
                buffer.extend(bytes(socket.read(min(available, allowance))))
                if len(buffer) >= _FRAME_HEADER_BYTES and expected is None:
                    declared = int.from_bytes(buffer[:_FRAME_HEADER_BYTES], "big")
                    if declared > MAX_MESSAGE_BYTES:
                        socket.abort()
                        raise InstanceServiceError("UNITI reply exceeds its safe limit")
                    expected = _FRAME_HEADER_BYTES + declared
                if expected is not None:
                    if len(buffer) > expected:
                        socket.abort()
                        raise InstanceServiceError("UNITI reply contains trailing bytes")
                    if len(buffer) == expected:
                        return bytes(buffer)
            if (
                socket.state() == QLocalSocket.LocalSocketState.UnconnectedState
                and (expected is None or len(buffer) < expected)
            ):
                raise InstanceServiceError("UNITI closed before replying")
            remaining = self._remaining_ms(deadline)
            if remaining <= 0:
                socket.abort()
                raise InstanceTimeoutError("UNITI request timed out waiting for a reply")
            socket.waitForReadyRead(min(remaining, 20))

    def _forward(self, request: InstanceRequest, timeout_ms: int) -> InstanceReply:
        frame = encode_request(request)
        deadline = time.monotonic() + timeout_ms / 1000
        socket = QLocalSocket()
        socket.setReadBufferSize(_MAX_FRAME_BYTES + 1)
        try:
            self._connect_secondary(socket, deadline)
            self._write_secondary(socket, frame, deadline)
            reply_frame = self._read_secondary(socket, deadline)
            try:
                return decode_reply(reply_frame)
            except InstanceProtocolError as exc:
                raise InstanceServiceError("UNITI returned an invalid local reply") from exc
        finally:
            socket.abort()

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.setReadBufferSize(_MAX_FRAME_BYTES + 1)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.setInterval(self._request_timeout_ms)
            peer = _Peer(bytearray(), None, timer)
            self._peers[socket] = peer
            socket.readyRead.connect(lambda socket=socket: self._read_peer(socket))
            socket.disconnected.connect(
                lambda socket=socket: self._forget_peer(socket)
            )
            timer.timeout.connect(lambda socket=socket: self._abort_peer(socket))
            timer.start()
            self._read_peer(socket)

    def _read_peer(self, socket: QLocalSocket) -> None:
        peer = self._peers.get(socket)
        if peer is None or peer.emitted:
            return
        while socket.bytesAvailable() > 0:
            allowance = _MAX_FRAME_BYTES + 1 - len(peer.buffer)
            if allowance <= 0:
                self._abort_peer(socket)
                return
            peer.buffer.extend(
                bytes(socket.read(min(socket.bytesAvailable(), allowance)))
            )
            if len(peer.buffer) >= _FRAME_HEADER_BYTES and peer.expected_bytes is None:
                declared = int.from_bytes(peer.buffer[:_FRAME_HEADER_BYTES], "big")
                if declared > MAX_MESSAGE_BYTES:
                    self._abort_peer(socket)
                    return
                peer.expected_bytes = _FRAME_HEADER_BYTES + declared
            expected = peer.expected_bytes
            if expected is not None and len(peer.buffer) > expected:
                self._abort_peer(socket)
                return
        expected = peer.expected_bytes
        if expected is None or len(peer.buffer) != expected:
            return
        try:
            request = decode_request(bytes(peer.buffer))
        except InstanceProtocolError:
            self._abort_peer(socket)
            return
        peer.request = request
        peer.emitted = True
        self.requestReceived.emit(socket, request)

    def reply(self, connection: QLocalSocket, result: InstanceReply) -> None:
        if not isinstance(connection, QLocalSocket):
            raise TypeError("connection must be a QLocalSocket")
        if not isinstance(result, InstanceReply):
            raise TypeError("result must be an InstanceReply")
        peer = self._peers.get(connection)
        if peer is None or not peer.emitted:
            raise InstanceServiceError("connection has no validated pending request")
        if peer.replied:
            raise InstanceServiceError("connection already has a reply")
        request = peer.request
        if request is None:
            raise InstanceServiceError("connection has no validated pending request")
        if result.accepted and tuple(
            outcome.path for outcome in result.outcomes
        ) != request.files:
            raise InstanceServiceError(
                "an accepted request requires one ordered outcome per requested path"
            )
        frame = encode_reply(result)
        peer.timer.stop()
        written = connection.write(frame)
        if written != len(frame):
            self._abort_peer(connection)
            raise InstanceServiceError("could not queue the local UNITI reply")
        peer.replied = True
        connection.flush()
        connection.disconnectFromServer()

    def _abort_peer(self, socket: QLocalSocket) -> None:
        peer = self._peers.pop(socket, None)
        if peer is not None:
            peer.timer.stop()
        socket.abort()
        socket.deleteLater()

    def _forget_peer(self, socket: QLocalSocket) -> None:
        peer = self._peers.pop(socket, None)
        if peer is not None:
            peer.timer.stop()
        socket.deleteLater()

    def close(self) -> None:
        if self._closed:
            return
        for socket in tuple(self._peers):
            self._abort_peer(socket)
        if self._server.isListening():
            self._server.close()
        if self._owns_lease:
            QLocalServer.removeServer(self.endpoint_name)
            self._lock.unlock()
            self._owns_lease = False
        self._closed = True


__all__ = [
    "InstanceRole",
    "InstanceService",
    "InstanceServiceError",
    "InstanceStart",
    "InstanceTimeoutError",
    "InstanceUnavailableError",
]
