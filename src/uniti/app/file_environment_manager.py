"""Service-owned isolated file-type environment controller (ADR-0013, Phase E2).

Owned by `UNITIService` alongside `documents` (`DocumentRegistry`) and
`recovery` (`RecoveryManager`) — not by `UNITIMainWindow` — because
environment identity is a per-document concern that must stay consistent
across every window a `Document` happens to be open in, exactly like those
two services already are (see `service.py`'s `UNITIService.__init__`).

Named `FileEnvironmentManager`, not `EnvironmentManager`: `uniti.bootstrap.
environment.EnvironmentManager` already owns Python venv/runtime bootstrap,
an unrelated domain — reusing that name here would give the codebase two
same-named classes with nothing in common.

`activate_for()` is deliberately stateless: it constructs, activates, and
returns one `Environment` instance per call rather than maintaining a
persistent per-document binding table (the way `RecoveryManager.attach`/
`detach` does for its own journal bindings). No environment registered here
yet needs to survive across calls — Phase E3/E4's JSON/XML/YAML environments
add only stateless decoration/validation. A persistent lifecycle is deferred
until a real environment actually needs to cache state across edits; wiring
attach/detach into every document open/close/replace call site in
`main_window.py` speculatively, before anything needs it, is exactly the
kind of premature framework this project's own operating rules warn against.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from uniti.core.document import Document
from uniti.core.environment import Environment, EnvironmentContext, PlainEnvironment
from uniti.core.syntax_profiles import profile_for_extension

logger = logging.getLogger("uniti.environment.file")

EnvironmentFactory = Callable[[], Environment]


class FileEnvironmentManager:
    """Resolve and activate isolated file-type environments for documents."""

    def __init__(self) -> None:
        self._factories: dict[str, EnvironmentFactory] = {
            PlainEnvironment.key: PlainEnvironment,
        }

    def register(self, key: str, factory: EnvironmentFactory) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("environment key must be a non-empty string")
        if not callable(factory):
            raise TypeError("environment factory must be callable")
        self._factories[key] = factory

    def resolve_key(self, suffix: str, overrides: dict[str, str] | None = None) -> str:
        """The environment key a document's extension resolves to.

        Delegates to the same `profile_for_extension` resolver the existing
        per-view syntax-profile system already uses (`syntax_extension_overrides`)
        — one resolution path, shared by both the new per-document environment
        default and the pre-existing per-view manual override.
        """

        return profile_for_extension(suffix, overrides).key

    def activate_for(self, document: Document, environment_key: str) -> Environment:
        """Activate the environment for `environment_key`.

        Falls back to `PlainEnvironment` on an unknown key or an activation
        failure. Never raises, and never leaves a document without a usable
        (if degraded) environment.
        """

        factory = self._factories.get(environment_key, PlainEnvironment)
        environment = factory()
        context = EnvironmentContext.for_document(document)
        try:
            environment.activate(context)
        except Exception:
            logger.exception(
                "environment %r failed to activate for %s; falling back to %s",
                environment_key,
                document.path,
                PlainEnvironment.key,
            )
            environment = PlainEnvironment()
            environment.activate(context)
        return environment


__all__ = ["EnvironmentFactory", "FileEnvironmentManager"]
