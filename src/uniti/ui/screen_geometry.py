"""Screen-aware geometry validation for persisted top-level window placement.

A saved `(x, y, width, height)` — a detached Find/Replace panel, a toggle
window (Character Inspector, Whitespace Legend, Compare) or a main window's
own `WindowRecord` — can name a position that no longer corresponds to any
connected screen, most commonly because it was last placed on an external
monitor that has since been unplugged, or on a larger display that has since
been replaced by a smaller one. Qt does not reliably reposition a window
whose explicit `setGeometry` call lands outside every current screen, so
restoring such a geometry verbatim can leave the window practically
unreachable (off-screen, with no visible way to drag it back). This module is
Qt-free of *behavior* but not of types — it takes screen rectangles as plain
`(x, y, width, height)` tuples so it can be tested without a real
multi-monitor `QApplication`.

"Reachable" means the window's title strip — its drag handle — is visible,
not merely that some pixel of the window overlaps a screen: the toggle
windows are frameless, with a custom title bar as the only way to move them.
"""

from __future__ import annotations

Geometry = tuple[int, int, int, int]

# Height of a frameless window's custom title bar, the strip that must stay
# on-screen so the window can be dragged back.
TITLE_STRIP_HEIGHT = 28
# The title strip must show at least this much width and height on one
# screen to be grabbable. Real title bars vary (28-31px) and a window may
# sit a pixel or two under a menu bar, so the height need not be complete.
MIN_VISIBLE_STRIP_WIDTH = 64
MIN_VISIBLE_STRIP_HEIGHT = 16
# Nominal height of a framed window's native title bar. `QWidget.geometry()`
# excludes it, and it is not measurable before the window is first shown.
NATIVE_TITLE_BAR_HEIGHT = 32


def _intersection(a: Geometry, b: Geometry) -> Geometry | None:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return None
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return (left, top, right - left, bottom - top)


def _title_strip(geometry: Geometry, frame_top: int) -> Geometry:
    """The window's drag handle: a framed window's native title bar (the
    `frame_top` pixels above its client geometry), else the top
    `TITLE_STRIP_HEIGHT` pixels of a frameless one."""

    x, y, width, height = geometry
    if frame_top > 0:
        return (x, y - frame_top, width, frame_top)
    return (x, y, width, min(TITLE_STRIP_HEIGHT, height))


def _is_reachable(geometry: Geometry, screens: tuple[Geometry, ...], frame_top: int) -> bool:
    strip = _title_strip(geometry, frame_top)
    _, _, strip_width, strip_height = strip
    needed_width = min(MIN_VISIBLE_STRIP_WIDTH, strip_width)
    needed_height = min(MIN_VISIBLE_STRIP_HEIGHT, strip_height)
    for screen in screens:
        visible = _intersection(strip, screen)
        if visible is None:
            continue
        # Enough of the strip must show both ways for it to be grabbable (a
        # title bar mostly under the menu bar or dock is not).
        if visible[3] >= needed_height and visible[2] >= needed_width:
            return True
    return False


def _bounds(screens: tuple[Geometry, ...]) -> Geometry:
    left = min(x for x, _, _, _ in screens)
    top = min(y for _, y, _, _ in screens)
    right = max(x + width for x, _, width, _ in screens)
    bottom = max(y + height for _, y, _, height in screens)
    return (left, top, right - left, bottom - top)


def _distance_to(screen: Geometry, geometry: Geometry) -> float:
    """Distance from the centre of `geometry` to the nearest point of
    `screen` (0 when the centre is inside it)."""

    x, y, width, height = geometry
    centre_x, centre_y = x + width / 2, y + height / 2
    screen_x, screen_y, screen_width, screen_height = screen
    dx = max(screen_x - centre_x, 0, centre_x - (screen_x + screen_width))
    dy = max(screen_y - centre_y, 0, centre_y - (screen_y + screen_height))
    return (dx * dx + dy * dy) ** 0.5


def nearest_screen(geometry: Geometry, screens: tuple[Geometry, ...]) -> Geometry:
    """The screen closest to `geometry`'s centre (the first on a tie)."""

    return min(screens, key=lambda screen: _distance_to(screen, geometry))


def _fit_within(geometry: Geometry, area: Geometry, frame_top: int) -> Geometry:
    """Cap `geometry`'s size to `area` and shift it fully inside, leaving
    room above it for a framed window's native title bar."""

    x, y, width, height = geometry
    area_x, area_y, area_width, area_height = area
    capped_width = max(1, min(width, area_width))
    capped_height = max(1, min(height, area_height - frame_top))
    new_x = min(max(x, area_x), area_x + area_width - capped_width)
    new_y = min(
        max(y, area_y + frame_top), area_y + area_height - capped_height
    )
    return (new_x, new_y, capped_width, capped_height)


def clamp_geometry_to_screens(
    geometry: Geometry,
    available_screens: tuple[Geometry, ...],
    *,
    frame_top: int = 0,
) -> Geometry:
    """Return a version of `geometry` that is reachable on one of
    `available_screens`' available areas.

    - Title strip visible and not larger than the combined screens:
      unchanged — a deliberate placement that hangs partly off an edge is
      left alone while its drag handle is still on-screen.
    - Larger than every screen combined (a bigger display was replaced by a
      smaller one but the origin still overlaps): capped to the combined
      screen area and shifted inside it.
    - Title strip not visible (the saved screen is gone, or the window sits
      mostly off-screen): kept at its saved width/height, capped to fit, and
      centered on the *nearest* available screen.

    `frame_top` is the height of a framed window's native title bar above
    its client geometry; leave it 0 for the frameless toggle windows. An
    empty `available_screens` (no screen information at all) returns
    `geometry` unchanged, rather than guessing.
    """

    if not available_screens:
        return geometry
    x, y, width, height = geometry
    reachable = _is_reachable(geometry, available_screens, frame_top)
    bounds = _bounds(available_screens)
    _, _, bounds_width, bounds_height = bounds
    oversize = width > bounds_width or height + frame_top > bounds_height
    if reachable and not oversize:
        return geometry
    if reachable:
        return _fit_within(geometry, bounds, frame_top)
    screen = nearest_screen(geometry, available_screens)
    screen_x, screen_y, screen_width, screen_height = screen
    clamped_width = max(1, min(width, screen_width))
    clamped_height = max(1, min(height, screen_height - frame_top))
    new_x = screen_x + max(0, (screen_width - clamped_width) // 2)
    new_y = (
        screen_y
        + frame_top
        + max(0, (screen_height - frame_top - clamped_height) // 2)
    )
    return (new_x, new_y, clamped_width, clamped_height)


def current_screen_geometries() -> tuple[Geometry, ...]:
    """The available (menu-bar/dock/taskbar-excluded) geometry of every
    currently connected screen, as plain tuples."""

    from PySide6.QtGui import QGuiApplication

    return tuple(
        (rect.x(), rect.y(), rect.width(), rect.height())
        for rect in (screen.availableGeometry() for screen in QGuiApplication.screens())
    )
