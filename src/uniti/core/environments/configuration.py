"""The configuration files that apply to a document (round 2, R8).

`configuration_files` lists them in the order they apply, for the
environment menu's **Configuration Files…**: built-in files (read-only),
the user's own files (`user_config`), the project's files, and stylesheets
loaded by hand. Rows for files that don't exist yet carry a template, so
they can be created. Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .user_config import REFERENCE_FOLDER, environment_folder, usfm_user_rules_path, usfm_versification_folder

BUILT_IN = "built-in"
YOURS = "yours"
PROJECT = "project"
LOADED = "loaded"


@dataclass(frozen=True, slots=True)
class ConfigurationFile:
    role: str
    path: Path | None
    kind: str  # BUILT_IN | YOURS | PROJECT | LOADED
    exists: bool
    is_folder: bool = False
    template: str | None = None  # contents for Create; None: can't be created
    note: str = ""

    @property
    def editable(self) -> bool:
        return self.kind != BUILT_IN and not self.is_folder


def _row(role: str, path: Path | None, kind: str, *, folder: bool = False, template: str | None = None, note: str = "") -> ConfigurationFile:
    exists = path is not None and (path.is_dir() if folder else path.is_file())
    return ConfigurationFile(role, path, kind, exists, folder, None if exists else template, note)


def reference_copy_path(environment_label: str, built_in: Path) -> Path | None:
    """Where a built-in file is copied to for reading (changing the copy has no effect)."""

    folder = environment_folder(environment_label)
    return None if folder is None else folder / REFERENCE_FOLDER / built_in.name


def configuration_files(environment_key: str, environment_label: str, document_path: Path | None, environment=None) -> tuple[ConfigurationFile, ...]:
    rows = [
        _row(
            f"Your {environment_label} configuration folder",
            environment_folder(environment_label),
            YOURS,
            folder=True,
            note="Your own files for this environment, in UNITI's user data.",
        )
    ]
    if environment_key == "usfm":
        rows.extend(_usfm_rows(document_path, environment))
    return tuple(rows)


def _usfm_rows(document_path: Path | None, environment) -> list[ConfigurationFile]:
    from .sfm.paratext_project import project_for_file
    from .sfm.style_layers import project_stylesheet_candidates
    from .sfm.usfm_baseline import uniti_builtin_path, usfm_baseline_path

    rows = [
        _row("Official USFM stylesheet", usfm_baseline_path(), BUILT_IN, note="Built in, read-only. Change markers in your rules or the project's custom.sty."),
        _row("UNITI built-in rules", uniti_builtin_path(), BUILT_IN, note="Built in, read-only. Override them in your rules."),
        _row(
            "Your rules (every USFM file)",
            usfm_user_rules_path(),
            YOURS,
            template=uniti_rules_template("your own rules for every USFM file"),
            note="Applies above the built-in rules and below each project's stylesheets.",
        ),
    ]
    if document_path is not None:
        folder = document_path.parent
        roles = {
            "custom.sty": "Project custom stylesheet",
            "shared/ptxprint/ptxprint-mods.sty": "PTXprint changes",
            "uniti.sty": "Project rules (UNITI only)",
        }
        for relative, _origin in project_stylesheet_candidates(document_path):
            role = roles.get(relative, f"Project stylesheet ({relative})")
            template = None
            if relative == "custom.sty":
                template = CUSTOM_STY_TEMPLATE
            elif relative == "uniti.sty":
                template = uniti_rules_template("this project's rules; Paratext and PTXprint never read this file")
            rows.append(_row(role, folder / relative, PROJECT, template=template))
        project = project_for_file(document_path)
        if project is not None:
            rows.append(_row("Project settings (Settings.xml)", folder / "Settings.xml", PROJECT, note="Paratext's project settings."))
            rows.append(_row("Project book names (BookNames.xml)", folder / "BookNames.xml", PROJECT))
            rows.append(_row("Project versification changes (custom.vrs)", folder / "custom.vrs", PROJECT))
    for layer in getattr(environment, "imported_stylesheets", ()) or ():
        rows.append(_row(f"Loaded stylesheet ({layer.name})", layer.path, LOADED, note="Loaded with Load Stylesheet… for this session."))
    rows.append(
        _row(
            "Your versification files",
            usfm_versification_folder(),
            YOURS,
            folder=True,
            note="Septuagint, Vulgate and Russian .vrs files copied from Paratext.",
        )
    )
    return rows


CUSTOM_STY_TEMPLATE = """# custom.sty - this project's stylesheet changes.
# Paratext, PTXprint and UNITI all read this file.
#
# Each record changes (or adds) one marker: \\Marker <name>, then its fields:
#
#   \\Marker nd
#   \\SmallCaps
#
# See docs/usfm-stylesheet-rules.md and docs/environments/usfm.md.
"""


def uniti_rules_template(purpose: str) -> str:
    """A `uniti.sty` to start from: what it is for, then UNITI's built-in
    rules commented out, to copy and change."""

    from .sfm.usfm_baseline import uniti_builtin_path

    lines = [
        f"# uniti.sty - {purpose}.",
        "#",
        "# Records whose \\Marker is a selector are UNITI presentation rules:",
        "#   \\Marker p+q1       a \\q1 paragraph straight after a \\p paragraph",
        "#   \\Marker f::caller  the caller of a footnote",
        "# A record with an ordinary marker name changes that marker's style.",
        "# Turn a flag off with '-' (\\Underline -).",
        "# Paragraph fields: \\Justification (Left, Center, Right, Both, Start, End), \\Hyphenate,",
        "# \\Direction (LTR, RTL, Auto), \\LeftMargin, \\RightMargin, \\FirstLineIndent, \\SpaceBefore,",
        "# \\SpaceAfter. Left, Right and the margins follow the paragraph's reading direction.",
        "# A character style's \\Direction (LTR, RTL) makes its text read that way in any paragraph.",
        "# See docs/usfm-stylesheet-rules.md for every field and selector.",
        "#",
        "# UNITI's built-in rules, for reference - remove the '# ' to use one:",
        "#",
    ]
    path = uniti_builtin_path()
    try:
        built_in = path.read_text(encoding="utf-8") if path is not None else ""
    except OSError:
        built_in = ""
    for line in built_in.splitlines():
        if line.startswith("#"):
            continue  # the built-in file's own header
        lines.append(f"# {line}" if line.strip() else "#")
    return "\n".join(lines).rstrip("#\n") + "\n"


__all__ = [
    "BUILT_IN",
    "CUSTOM_STY_TEMPLATE",
    "ConfigurationFile",
    "LOADED",
    "PROJECT",
    "YOURS",
    "configuration_files",
    "reference_copy_path",
    "uniti_rules_template",
]
