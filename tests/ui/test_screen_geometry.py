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


def test_partial_overlap_still_counts_as_reachable():
    # Only a corner of the saved geometry is on-screen — still draggable,
    # so it's left alone rather than "corrected" away from the user's
    # deliberate placement.
    geometry = (1900, 1060, 400, 300)
    screens = ((0, 0, 1920, 1080),)
    assert clamp_geometry_to_screens(geometry, screens) == geometry
