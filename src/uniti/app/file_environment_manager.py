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

ADR-0014 adds `active_for()`: environment *commands* (menus/tools) need one
live instance per document, so the manager keeps a weak, per-document cache
alongside the stateless `activate_for()`. It is keyed weakly by `Document`
so a closed document's environment is dropped with it — no attach/detach
call sites needed. A failed activation is remembered as "plain text within
the environment": the document keeps its environment identity (so its menu
still names it and can explain what happened), but every enhanced
capability is off and Plain behavior applies.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from uniti.core.document import Document
from uniti.core.environment import Environment, EnvironmentContext, PlainEnvironment
from uniti.core.environments.catalog import ENVIRONMENTS, environment_key_for_extension, environment_key_for_path

logger = logging.getLogger("uniti.environment.file")

EnvironmentFactory = Callable[[], Environment]


@dataclass(frozen=True, slots=True)
class ActiveEnvironment:
    """One document's live environment.

    `failed` means activation raised and `environment` is the Plain fallback
    standing in for `key` ("plain text within the environment").
    """

    key: str
    environment: Environment
    failed: bool = False


class FileEnvironmentManager:
    """Resolve and activate isolated file-type environments for documents."""

    def __init__(self) -> None:
        self._factories: dict[str, EnvironmentFactory] = {
            PlainEnvironment.key: PlainEnvironment,
        }
        self._active: weakref.WeakKeyDictionary[Document, ActiveEnvironment] = (
            weakref.WeakKeyDictionary()
        )

    @classmethod
    def with_builtin_environments(cls) -> "FileEnvironmentManager":
        """A manager with every catalog environment registered (ADR-0014)."""

        manager = cls()
        for descriptor in ENVIRONMENTS:
            manager.register(descriptor.key, descriptor.factory)
        return manager

    def is_registered(self, key: str) -> bool:
        return key in self._factories

    def register(self, key: str, factory: EnvironmentFactory) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("environment key must be a non-empty string")
        if not callable(factory):
            raise TypeError("environment factory must be callable")
        self._factories[key] = factory

    def resolve_key(self, suffix: str, overrides: Mapping[str, str] | None = None) -> str:
        """The environment key a document's extension resolves to.

        Delegates to the same `profile_for_extension` resolver the existing
        per-view syntax-profile system already uses (`syntax_extension_overrides`)
        — one resolution path, shared by both the new per-document environment
        default and the pre-existing per-view manual override.
        """

        return environment_key_for_extension(suffix, overrides)

    def resolve_path_key(self, path, overrides: Mapping[str, str] | None = None) -> str:
        """The environment key the file at `path` resolves to: its
        extension's, or Plain Text when that environment needs a project
        the file isn't in (round 3 T1)."""

        return environment_key_for_path(path, overrides)

    def activate_for(self, document: Document, environment_key: str) -> Environment:
        """Activate the environment for `environment_key`.

        Falls back to `PlainEnvironment` on an unknown key or an activation
        failure. Never raises, and never leaves a document without a usable
        (if degraded) environment.
        """

        factory = self._factories.get(environment_key, PlainEnvironment)
        context = EnvironmentContext.for_document(document)
        try:
            environment = factory()
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


    def active_for(self, document: Document, environment_key: str) -> ActiveEnvironment:
        """`document`'s live environment for `environment_key`, activating on first use.

        Cached per document; a different key (the document was reassigned)
        deactivates the old instance and activates the new one. Never raises.
        """

        current = self._active.get(document)
        if current is not None and current.key == environment_key:
            return current
        if current is not None:
            self._deactivate(current)
        environment = self.activate_for(document, environment_key)
        failed = (
            environment_key != PlainEnvironment.key
            and environment_key in self._factories
            and isinstance(environment, PlainEnvironment)
        )
        active = ActiveEnvironment(environment_key, environment, failed)
        self._active[document] = active
        return active

    def release(self, document: Document) -> None:
        current = self._active.pop(document, None)
        if current is not None:
            self._deactivate(current)

    @staticmethod
    def _deactivate(active: ActiveEnvironment) -> None:
        try:
            active.environment.deactivate()
        except Exception:
            logger.exception("environment %r failed to deactivate", active.key)


__all__ = ["ActiveEnvironment", "EnvironmentFactory", "FileEnvironmentManager"]
