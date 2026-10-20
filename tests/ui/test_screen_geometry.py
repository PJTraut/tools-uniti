from uniti.ui.screen_geometry import clamp_geometry_to_screens


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


def test_geometry_larger_than_the_available_screen_is_capped_to_fit():
    geometry = (5000, 5000, 3000, 2000)
    screens = ((0, 0, 1920, 1080),)
    _, _, width, height = clamp_geometry_to_screens(geometry, screens)
    assert width == 1920
    assert height == 1080


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
