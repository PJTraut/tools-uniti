"""Built-in isolated file-type environments (ADR-0013, Phase E3/E4).

Each module here is a self-contained `Environment` implementation. This
package intentionally does not know about `FileEnvironmentManager`
(`app/file_environment_manager.py`) or how environments get registered —
that composition happens at the app layer (`app/service.py`), keeping the
dependency direction app -> core, not core -> app.
"""

from __future__ import annotations

from .json_environment import JsonEnvironment

__all__ = ["JsonEnvironment"]
