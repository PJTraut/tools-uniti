"""Portable modifier-only shortcut for temporary Unicode inspection."""

MODIFIER_NAMES = ("Ctrl", "Alt", "Shift", "Meta")
DEFAULT_INSPECTION_MODIFIERS = "Ctrl+Alt"


def normalize_inspection_modifiers(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("inspection modifiers must be a string")
    if value == "":
        return ""
    names = value.split("+")
    if (
        len(names) < 2
        or len(set(names)) != len(names)
        or any(name not in MODIFIER_NAMES for name in names)
    ):
        raise ValueError("Choose at least two modifiers, or clear all to disable inspection.")
    return "+".join(name for name in MODIFIER_NAMES if name in names)
