# Floating-Window Positions Across Screen Changes — Plan

Date: 2026-10-20
Status: **P1 built and pushed 2026-10-20 (`c532f07`); P2 (layouts per screen configuration) built 2026-10-20, not yet checked in the live app on a real multi-monitor setup.**
Origin: the user, 2026-10-20: "review all floating window restore positions, when switching between single and multi monitor and/or resolution variance of matched monitors", then "store layouts per screen configuration, when screen configuration change, revert to previous state for known configs, reset all to default for new config? review this" and, on the review's counter-proposal, "adapt/scale is fine".
Builds on: the detached Find/Replace panel's clamp (BF-0xx, `screen_geometry.py`), the generic toggle-window manager (`toggle_window.py`) and the session `WindowRecord`.

## The problem in one paragraph

A saved window rectangle names absolute screen coordinates. Unplug the external monitor, swap it for a smaller display, or change its resolution, and the rectangle can land off every screen. The toggle windows (Character Inspector, Whitespace Legend, Compare) and Find are frameless with a custom title bar as their only drag handle, so one that restores off-screen cannot be moved back, and because a toggle window opens and closes on the same hotkey it cannot even be summoned again. Only Find was protected, and only against "no pixel overlaps any screen".

## What was checked first

Code read 2026-10-20 (nothing run on real multi-monitor hardware):

1. **Only Find was clamped.** `set_detached_geometry` was the one caller of `clamp_geometry_to_screens`. Character Inspector, Whitespace Legend and Compare restored `toggle_window_geometry` verbatim (`toggle_window.py`), and `restore_window_record` restored the main window's rectangle verbatim.
2. **The clamp accepted any overlap.** One pixel on a screen counted as reachable (a test locked that in), so a window whose title bar was above the screen but whose bottom edge overlapped was left alone.
3. **Nothing was capped when a window overlapped a screen but was bigger than it.** A 2560×1440 monitor replaced by a 1440×900 one left the window hanging off both edges.
4. **A maximized window saved the screen-sized rectangle.** `export_window_record` saved `geometry()`, which Qt reports as the maximized rectangle, so un-maximizing after a restart on a smaller monitor restored a screen-sized "normal" window.
5. **The fallback was `screens[0]`**, not the nearest screen.
6. **No memory per screen setup.** One absolute rectangle per window. When the OS moves windows on an unplug, the move events overwrite the saved external-monitor position, and docking again does not bring the layout back. Nothing listens for screens being added or removed.

## Decisions

- **P1 first (the safe part):** make the clamp strict and complete, apply it to every restore path, save the normal rectangle of a maximized window.
- **Layouts per screen configuration (P2):** one layout per set of connected screens, keyed by a signature of each screen's identity (name, maker, model, serial), origin, size and scale, independent of list order. A known configuration puts everything back exactly; **a new one is adapted from the previous layout, not reset** (the user agreed). Reset would punish every projector, Sidecar, screen-sharing or remote-desktop session, all of which appear as extra screens.
- **Adapt means scale.** Main windows keep their relative position and scale with the screen (the left half of a 2560×1440 display becomes the left half of a 1440×900 one). Tool windows keep their size, so they stay readable, and only their position scales. A window follows the same monitor if it is still connected, else the screen in the same list position, else the primary.
- **Settle before acting.** A hot-plug emits several signals and sleep/wake can remove and re-add a monitor within seconds, so the manager waits until the screens stop signalling (750 ms). Settling to the *same* configuration still re-applies its layout, undoing what the OS did meanwhile.
- **Never record the OS's shuffle.** Layouts are recorded by polling for geometry that held still across two polls under an unchanged screen signature, not by watching every move. A transition always reaches the settle step first.
- **Bounded.** At most eight layouts, least recently recorded dropped first.
- **A separate file** (`window-layouts.json`, next to the settings), an atomic JSON store like Recent Projects, rather than new `Settings` fields: windows hold their own copies of the settings dataclass, and layouts are per machine.
- **No session-manifest change.** The layout book records which configuration the last recording was made under; a different current configuration at startup means the screens changed while UNITI was closed, and the restored windows are moved then.

## Phases

### P1 — Clamp every restore path, save the normal rectangle

Built 2026-10-20, pushed in `c532f07`.

- `screen_geometry.clamp_geometry_to_screens`: a window is reachable when at least 64 px wide and 16 px tall of its title strip (a frameless window's top 28 px; a framed window's native title bar, `frame_top`) is on one screen; a window larger than all screens combined is capped and shifted inside; an unreachable one keeps its size (capped) and is centred on the **nearest** screen.
- `ToggleWindowManager.toggle` clamps the persisted geometry before building any toggle window; `restore_window_record` clamps the main window's.
- `export_window_record` saves `normalGeometry()` for a maximized, fullscreen or minimized window.
- Three existing tests that relied on a window wider than the 800 px offscreen screen round-tripping unchanged now use on-screen geometries.

### P2 — Layouts per screen configuration

Built 2026-10-20.

- `uniti/app/window_layouts.py` (Qt-free): `ScreenSpec`, `screen_signature`, `Placement`, `Layout`, `LayoutBook` (bounded, newest first), `WindowLayoutStore`. Loading never repairs or writes a damaged file; it reads as an empty book.
- `screen_geometry.adapt_geometry`: the pairing and scaling above, then the clamp against the targets' available areas.
- `uniti/ui/screen_layout_manager.py`: `ScreenLayoutManager` watches `screenAdded`, `screenRemoved`, `primaryScreenChanged` and each screen's `geometryChanged`, polls (1 s) to record, settles (750 ms) and applies. It records every main window's placement, the detached Find geometry and each toggle window's geometry (open ones live, closed ones through `note_toggle_closed`).
- `UNITIMainWindow.export_window_placement` / `apply_window_placement`: the normal rectangle plus state, and moving a live window (a maximized one returns to normal first so it can change screens) without showing or hiding it.
- `ToggleWindowManager` reopens a window where `service.screen_layouts` says for the current configuration and tells it where one was left; `service.find_replace` does the same for Find. `_start_screen_layouts` (application startup) creates and starts the manager once the session's windows exist; `_execute_quit` records the final positions before the windows close.

## Not done

- **Not checked on a real second monitor, a real unplug, or sleep/wake on macOS.** Everything is tested with fake screen lists and the offscreen platform. `normalGeometry()` on native Cocoa for a maximized window is unconfirmed. See the live checks below.
- A window's *tabs* are not part of a layout: it is only about where windows are, not what is in them.
- No UI to forget a layout; the store is bounded instead.
- Other dialogs (Hotkeys, Theme Editor, Recovery Center, …) are modal or short-lived and use default sizes; none persists a position.

## Live checks (not yet done)

With a laptop and an external monitor:

1. Open Find (detached), Character Inspector and Compare on the external monitor; maximize the main window there. Quit. Unplug the monitor. Launch: every window is on the laptop, scaled, and the main window un-maximizes to a laptop-sized rectangle.
2. Replug with UNITI running: the windows jump back to where they were.
3. Put the external monitor to a different scaled resolution: a new layout adapts from the last one; switching back restores the first exactly.
4. Sleep and wake with the monitor attached: windows stay where they were.
5. Unplug while a toggle window is open on the external monitor: it moves onto the laptop and its hotkey still closes it.
