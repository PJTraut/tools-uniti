from uniti.ui.screen_geometry import adapt_geometry, clamp_geometry_to_screens


def test_geometry_overlapping_a_screen_is_left_unchanged():
    geometry = (100, 100, 400, 300)
    screens = ((0, 0, 1920, 1080),)
    assert clamp_geometry_to_screens(geometry, screens) == geometry


def test_geometry_on_a_since_removed_screen_is_recentered_on_the_first_available_one():
    # Saved while a second monitor to the right (x=1920..3840) existed;
    # that monitor has since been unplugged, leaving only the primary one.
    geometry = (2200, 200, 820, 320)
    screens = ((0, 0, 1920, 1080),)
    result = clamp_geometry_to_screens(geometry, screens)
    x, y, width, height = result
    assert width == 820
    assert height == 320
    assert 0 <= x <= 1920 - width
    assert 0 <= y <= 1080 - height


def test_unreachable_geometry_larger_than_the_screen_shrinks_in_proportion_below_the_full_screen():
    geometry = (5000, 5000, 3000, 2000)
    screens = ((0, 0, 1920, 1080),)
    x, y, width, height = clamp_geometry_to_screens(geometry, screens)
    assert width <= 1920 * 0.8 and height <= 1080 * 0.8
    assert abs(width / height - 3000 / 2000) < 0.01  # proportions kept
    assert 0 <= x and x + width <= 1920 and 0 <= y and y + height <= 1080


def test_unreachable_geometry_that_already_fits_comfortably_keeps_its_size():
    geometry = (5000, 5000, 900, 600)
    screens = ((0, 0, 1920, 1080),)
    _, _, width, height = clamp_geometry_to_screens(geometry, screens)
    assert (width, height) == (900, 600)


def test_geometry_overlapping_any_one_of_several_screens_is_left_unchanged():
    geometry = (2000, 100, 400, 300)
    screens = ((0, 0, 1920, 1080), (1920, 0, 1920, 1080))
    assert clamp_geometry_to_screens(geometry, screens) == geometry


def test_no_screen_information_leaves_geometry_unchanged():
    geometry = (2200, 200, 820, 320)
    assert clamp_geometry_to_screens(geometry, ()) == geometry


def test_window_hanging_off_an_edge_is_left_alone_while_its_title_strip_is_visible():
    # Deliberately dragged mostly off the right edge and below the bottom,
    # but the drag handle is still there to grab.
    screens = ((0, 0, 1920, 1080),)
    assert clamp_geometry_to_screens((1820, 100, 400, 300), screens) == (1820, 100, 400, 300)
    assert clamp_geometry_to_screens((100, 1040, 400, 300), screens) == (100, 1040, 400, 300)


def test_corner_sliver_with_the_title_strip_off_screen_is_recentered():
    # Only the top-left corner of the body overlaps the screen: it overlaps,
    # but the title strip that drags it is not grabbable.
    screens = ((0, 0, 1920, 1080),)
    x, y, width, height = clamp_geometry_to_screens((1900, 1070, 400, 300), screens)
    assert (width, height) == (400, 300)
    assert 0 <= x <= 1920 - width
    assert 0 <= y <= 1080 - height


def test_window_whose_title_strip_is_above_the_screen_is_recentered():
    # Dragged up so the title bar is off the top while the body still
    # overlaps the screen -- unreachable for a frameless window.
    screens = ((0, 0, 1920, 1080),)
    _, y, _, height = clamp_geometry_to_screens((200, -100, 400, 300), screens)
    assert 0 <= y <= 1080 - height


def test_title_strip_with_too_little_width_visible_is_recentered():
    screens = ((0, 0, 1920, 1080),)
    # Only 30 px of the strip's width sits on the screen.
    x, _, width, _ = clamp_geometry_to_screens((1890, 100, 400, 300), screens)
    assert 0 <= x <= 1920 - width


def test_window_larger_than_a_shrunk_screen_is_capped_even_though_it_overlaps():
    # The 2560x1440 monitor was replaced by a 1440x900 one; the saved origin
    # still overlaps it but the window hangs off both far edges.
    screens = ((0, 0, 1440, 900),)
    assert clamp_geometry_to_screens((100, 100, 2400, 1300), screens) == (0, 0, 1440, 900)


def test_window_spanning_two_screens_is_left_alone_when_it_fits_their_union():
    screens = ((0, 0, 1920, 1080), (1920, 0, 1920, 1080))
    geometry = (1000, 100, 2000, 500)
    assert clamp_geometry_to_screens(geometry, screens) == geometry


def test_window_on_a_screen_left_of_the_primary_is_left_alone():
    screens = ((-1920, 0, 1920, 1080), (0, 0, 1920, 1080))
    geometry = (-1500, 100, 800, 600)
    assert clamp_geometry_to_screens(geometry, screens) == geometry


def test_unreachable_window_goes_to_the_nearest_screen_not_the_first():
    # Saved far to the right of a two-screen setup: the nearest screen is the
    # right-hand one, not screens[0].
    screens = ((0, 0, 1920, 1080), (1920, 0, 1920, 1080))
    x, y, width, height = clamp_geometry_to_screens((6000, 200, 400, 300), screens)
    assert (width, height) == (400, 300)
    assert 1920 <= x <= 3840 - width
    assert 0 <= y <= 1080 - height


def test_unreachable_window_left_of_everything_goes_to_the_leftmost_screen():
    screens = ((0, 0, 1920, 1080), (1920, 0, 1920, 1080))
    x, _, width, _ = clamp_geometry_to_screens((-5000, 200, 400, 300), screens)
    assert 0 <= x <= 1920 - width


def test_framed_window_keeps_its_native_title_bar_below_the_top_of_the_screen():
    screens = ((0, 25, 1920, 1055),)  # macOS: available area starts under the menu bar
    # Client area at y=40: its 32px title bar would sit at 8, mostly under the
    # 25px menu bar and not grabbable.
    _, y, _, _ = clamp_geometry_to_screens((100, 40, 800, 600), screens, frame_top=32)
    assert y >= 25 + 32
    # A pixel or two under the menu bar is tolerated: the OS keeps it usable.
    geometry = (100, 54, 800, 600)
    assert clamp_geometry_to_screens(geometry, screens, frame_top=32) == geometry
    # With room for the title bar the placement is untouched.
    geometry = (100, 80, 800, 600)
    assert clamp_geometry_to_screens(geometry, screens, frame_top=32) == geometry


def test_framed_window_is_capped_so_its_title_bar_and_body_fit_the_screen():
    screens = ((0, 25, 1440, 875),)
    x, y, width, height = clamp_geometry_to_screens((0, 57, 3000, 3000), screens, frame_top=32)
    assert (x, width) == (0, 1440)
    assert y == 25 + 32
    assert y + height <= 25 + 875


LAPTOP = ("laptop", (0, 0, 1440, 900))
BIG = ("big", (0, 0, 2560, 1440))
LEFT = ("left", (0, 0, 1920, 1080))
RIGHT = ("right", (1920, 0, 1920, 1080))


def test_adapt_to_an_identical_screen_changes_nothing():
    geometry = (300, 200, 800, 600)
    assert adapt_geometry(geometry, (BIG,), (BIG,), scale_size=True) == geometry
    assert adapt_geometry(geometry, (BIG,), (BIG,), scale_size=False) == geometry


def test_adapt_scales_a_main_window_to_a_smaller_screen_in_proportion():
    # The left half of a 2560x1440 display becomes the left half of 1440x900.
    assert adapt_geometry((0, 0, 1280, 1440), (BIG,), (LAPTOP,), scale_size=True) == (0, 0, 720, 900)


def test_adapt_keeps_a_tool_window_size_and_moves_its_centre_proportionally():
    # Centre at (1900, 1100) of 2560x1440 -> (1900/2560, 1100/1440) of 1440x900.
    x, y, width, height = adapt_geometry((1700, 1000, 400, 200), (BIG,), (LAPTOP,), scale_size=False)
    assert (width, height) == (400, 200)
    assert abs((x + width / 2) - 1900 / 2560 * 1440) <= 1
    assert abs((y + height / 2) - 1100 / 1440 * 900) <= 1


def test_adapt_shrinks_a_tool_window_larger_than_the_new_screen_in_proportion():
    _, _, width, height = adapt_geometry((0, 0, 3000, 2000), (BIG,), (LAPTOP,), scale_size=False)
    assert width <= 1440 * 0.8 and height <= 900 * 0.8
    assert abs(width / height - 1.5) < 0.01


def test_adapt_leaves_a_tool_window_that_fits_comfortably_at_its_size():
    _, _, width, height = adapt_geometry((100, 100, 900, 600), (BIG,), (LAPTOP,), scale_size=False)
    assert (width, height) == (900, 600)


def test_adapt_follows_the_same_monitor_when_the_arrangement_changes():
    # "right" used to sit at x=1920; now it is on the left of the primary.
    target = (("left", (0, 0, 1920, 1080)), ("right", (-1920, 0, 1920, 1080)))
    x, y, width, height = adapt_geometry((2400, 100, 800, 600), (LEFT, RIGHT), target, scale_size=True)
    assert -1920 <= x and x + width <= 0
    assert (width, height) == (800, 600)


def test_adapt_sends_a_window_from_a_removed_monitor_to_the_screen_in_its_list_position():
    # Only "left" remains; a window that lived on "right" lands on the primary.
    x, y, width, height = adapt_geometry((2400, 100, 800, 600), (LEFT, RIGHT), (LEFT,), scale_size=True)
    assert 0 <= x and x + width <= 1920
    assert 0 <= y and y + height <= 1080


def test_adapt_pairs_identically_named_monitors_by_their_order():
    first = ("same", (0, 0, 1920, 1080))
    second = ("same", (1920, 0, 1920, 1080))
    moved = (("same", (0, 0, 1920, 1080)), ("same", (2000, 0, 1920, 1080)))
    x, _, width, _ = adapt_geometry((2000, 100, 800, 600), (first, second), moved, scale_size=True)
    assert 2000 <= x and x + width <= 3920


def test_adapt_without_source_screens_is_just_a_clamp():
    assert adapt_geometry((9000, 100, 400, 300), (), (LEFT,), scale_size=True) == clamp_geometry_to_screens(
        (9000, 100, 400, 300), ((0, 0, 1920, 1080),)
    )


def test_adapt_clamps_against_the_available_area_when_given():
    # The target's full rectangle includes a 25px menu bar the window must avoid.
    result = adapt_geometry(
        (0, 0, 1000, 700), (BIG,), (LAPTOP,), scale_size=False,
        target_available=((0, 25, 1440, 875),), frame_top=32,
    )
    assert result[1] >= 25 + 32


def test_first_run_geometry_sits_inside_the_primary_available_area():
    from PySide6.QtWidgets import QApplication

    from uniti.ui.screen_geometry import first_run_geometry

    app = QApplication.instance() or QApplication([])

    x, y, width, height = first_run_geometry(820, 320)
    area = app.primaryScreen().availableGeometry()
    assert (width, height) == (820, 320)
    assert x > area.x() and y > area.y()
