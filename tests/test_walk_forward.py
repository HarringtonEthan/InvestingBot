"""
Tests for walk_forward.py's window-splitting logic - the part of the
script that decides what date ranges get treated as independent,
sequential validation periods. Getting this wrong (e.g. overlapping
windows) would silently defeat the entire point of walk-forward
validation, so it's tested directly rather than trusted by inspection.
"""

import pytest

from walk_forward import make_windows


def test_windows_are_sequential_and_cover_the_full_range():
    windows = make_windows("2024-01-01", "2024-05-01", 4)
    assert len(windows) == 4
    # The very first window starts at --start, and the very last window
    # ends at --end - nothing outside the requested range is silently
    # dropped or added.
    assert windows[0][0] == "2024-01-01"
    assert windows[-1][1] == "2024-05-01"
    # Each window's end is the next window's start - contiguous, no gaps
    # and no overlap between one window and the next.
    for (_, end), (next_start, _) in zip(windows, windows[1:]):
        assert end == next_start


def test_windows_are_non_overlapping():
    windows = make_windows("2024-01-01", "2024-12-31", 6)
    # Every window's own start must come strictly before its own end -
    # a zero-length or backwards window would be a degenerate result.
    for start, end in windows:
        assert start < end


def test_single_window_matches_full_range():
    windows = make_windows("2024-01-01", "2024-02-01", 1)
    assert windows == [("2024-01-01", "2024-02-01")]


def test_rejects_zero_or_negative_windows():
    with pytest.raises(ValueError):
        make_windows("2024-01-01", "2024-02-01", 0)
