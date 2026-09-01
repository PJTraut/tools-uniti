#!/usr/bin/env python3
"""Select Python 3.12+ and delegate to UNITI's standard-library bootstrap."""

import json
import os
import platform
import subprocess
import sys


_PROBE = (
    "import json,sys;"
    "print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable}))"
)


def _candidate_commands(environ, executable, platform_name):
    commands = []
    override = environ.get("UNITI_PYTHON")
    if override:
        commands.append((override,))
    commands.append((executable,))
    commands.append(("python3",))
    for minor in range(15, 11, -1):
        commands.append(("python3.%d" % minor,))
    if platform_name.startswith("win"):
        commands.append(("py", "-3"))
    unique = []
    for command in commands:
        if command not in unique:
            unique.append(command)
    return tuple(unique)


def _probe(command):
    try:
        completed = subprocess.run(
            list(command) + ["-c", _PROBE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
            timeout=10,
            shell=False,
        )
        if completed.returncode != 0:
            return None
        payload = json.loads(completed.stdout)
        return tuple(int(value) for value in payload["version"][:3])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def _select_supported(candidates, probe=_probe):
    for command in candidates:
        version = probe(command)
        if version is not None and version >= (3, 12, 0):
            return command
    return None


def _delegate(arguments):
    repository = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(repository, "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from uniti.bootstrap.cli import main

    return int(main(arguments))


def main(arguments=None):
    args = list(sys.argv[1:] if arguments is None else arguments)
    if sys.version_info[:3] >= (3, 12, 0):
        return _delegate(args)
    candidates = _candidate_commands(os.environ, sys.executable, platform.system().lower())
    selected = _select_supported(candidates)
    if selected is None:
        sys.stderr.write("UNITI requires an installed Python 3.12 or newer.\n")
        return 10
    completed = subprocess.run(
        list(selected) + [os.path.abspath(__file__)] + args,
        check=False,
        shell=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
