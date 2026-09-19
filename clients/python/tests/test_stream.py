"""The placement rule, the same cases the portal's stream.test.ts pins."""

from tadas.client.stream import Gap, Next, Seen, is_last_page, place


def test_the_first_push_sets_the_cursor() -> None:
    assert place(None, 5) == Next("next", 5)


def test_the_next_seq_advances() -> None:
    assert place(7, 8) == Next("next", 8)


def test_a_seq_at_or_behind_the_cursor_is_seen() -> None:
    assert place(7, 7) == Seen("seen")
    assert place(7, 3) == Seen("seen")


def test_a_skipped_seq_names_the_replay_point() -> None:
    assert place(7, 9) == Gap("gap", 7)
    assert place(7, 100) == Gap("gap", 7)


def test_paging_ends_on_a_short_page() -> None:
    assert is_last_page(200, 200) is False
    assert is_last_page(12, 200) is True
