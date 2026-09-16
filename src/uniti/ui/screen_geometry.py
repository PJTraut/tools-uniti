"""Screen-aware geometry validation for persisted top-level window placement.

A saved `(x, y, width, height)` — the detached Find/Replace panel's own
geometry (`Settings.find_replace_geometry`, a session `FindReplaceRecord`,
or its own remembered pre-attach placement) — can name a position that no
longer corresponds to any connected screen, most commonly because it was
last placed on an external monitor that has since been unplugged. Qt does
not reliably reposition a window whose explicit `setGeometry` call lands
outside every current screen, so restoring such a geometry verbatim can
leave the panel practically unreachable (off-screen, with no visible way
to drag it back). This module is Qt-free of *behavior* but not of types —
it takes screen rectangles as plain `(x, y, width, height)` tuples so it
can be tested without a real multi-monitor `QApplication`.
"""

from __future__ import annotations

Geometry = tuple[int, int, int, int]


def _intersects(a: Geometry, b: Geometry) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def clamp_geometry_to_screens(
    geometry: Geometry,
    available_screens: tuple[Geometry, ...],
) -> Geometry:
    """Return `geometry` unchanged if it overlaps at least one of
    `available_screens`'s available areas; otherwise reposition it (kept at
    its saved width/height, capped to fit) centered on the first available
    screen. An empty `available_screens` (no screen information at all)
    also returns `geometry` unchanged, rather than guessing.
    """

    if not available_screens:
        return geometry
    if any(_intersects(geometry, screen) for screen in available_screens):
        return geometry
    _, _, width, height = geometry
    screen_x, screen_y, screen_width, screen_height = available_screens[0]
    clamped_width = max(1, min(width, screen_width))
    clamped_height = max(1, min(height, screen_height))
    new_x = screen_x + max(0, (screen_width - clamped_width) // 2)
    new_y = screen_y + max(0, (screen_height - clamped_height) // 2)
    return (new_x, new_y, clamped_width, clamped_height)


def current_screen_geometries() -> tuple[Geometry, ...]:
    """The available (menu-bar/dock/taskbar-excluded) geometry of every
    currently connected screen, as plain tuples."""

    from PySide6.QtGui import QGuiApplication

    return tuple(
        (rect.x(), rect.y(), rect.width(), rect.height())
        for rect in (screen.availableGeometry() for screen in QGuiApplication.screens())
    )
