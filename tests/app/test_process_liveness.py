from __future__ import annotations


def test_windows_process_liveness_never_uses_posix_signal_zero(monkeypatch):
    from uniti.app import process_liveness

    monkeypatch.setattr(process_liveness.sys, "platform", "win32")
    monkeypatch.setattr(
        process_liveness.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("os.kill(pid, 0) sends CTRL_C_EVENT on Windows")
        ),
    )
    monkeypatch.setattr(
        process_liveness,
        "_windows_process_is_live",
        lambda pid: pid == 123,
    )

    assert process_liveness.process_is_live(123) is True
    assert process_liveness.process_is_live(456) is False
    assert process_liveness.process_is_live(0) is False
