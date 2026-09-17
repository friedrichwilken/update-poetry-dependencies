from updater.textcap import TAIL_CHARS, TAIL_LINES, capture_tail, strip_ansi


def test_strip_ansi_removes_color_codes():
    colored = "\x1b[31mred text\x1b[0m plain"
    assert strip_ansi(colored) == "red text plain"


def test_strip_ansi_removes_cursor_movement_sequences():
    text = "loading\x1b[2K\x1b[1Gdone"
    assert strip_ansi(text) == "loadingdone"


def test_strip_ansi_leaves_plain_text_untouched():
    assert strip_ansi("nothing special here") == "nothing special here"


def test_capture_tail_keeps_last_n_lines():
    text = "\n".join(f"line{i}" for i in range(100))
    tail = capture_tail(text, max_lines=5)
    assert tail == "\n".join(f"line{i}" for i in range(95, 100))


def test_capture_tail_returns_everything_when_under_the_limit():
    text = "line1\nline2\nline3"
    assert capture_tail(text, max_lines=40) == text


def test_capture_tail_strips_ansi_before_tailing():
    text = "\x1b[31mline1\x1b[0m\nline2"
    assert capture_tail(text) == "line1\nline2"


def test_capture_tail_caps_total_characters():
    text = "a" * 10000
    tail = capture_tail(text, max_lines=40, max_chars=100)
    assert len(tail) == 100
    assert tail == "a" * 100


def test_capture_tail_of_empty_text_is_empty():
    assert capture_tail("") == ""
    assert capture_tail("\n\n\n") == ""


def test_default_caps_match_documented_values():
    assert TAIL_LINES == 40
    assert TAIL_CHARS >= 1000
