import pytest

from omnicore.text.title_format import short_title


@pytest.mark.parametrize(
    "original,expected",
    [
        ('"Rozmowa na temat: OmniCore RC.4 — CUDA"', "OmniCore RC.4 — CUDA"),
        (
            "Title: Conversation about FastAPI streaming cancellation",
            "FastAPI streaming cancellation",
        ),
        (
            "Pytanie dotyczące konfiguracji serwera Linux i telefonów",
            "konfiguracji serwera Linux i telefonów",
        ),
        ("```\nOmniCore RC.5 — API\n```", "OmniCore RC.5 — API"),
        ("Zażółć gęślą jaźń", "Zażółć gęślą jaźń"),
        ("A" * 100, None),
        ("<script>secret</script>", None),
    ],
)
def test_deterministic_short_titles_preserve_words(original, expected):
    assert short_title(original) == expected


def test_title_limit_never_splits_a_word_or_exceeds_budget():
    title = short_title("Konfiguracja technicznego serwera wielowątkowego i adapterów API", 35)
    assert title == "Konfiguracja technicznego serwera"
    assert len(title) <= 35
    assert len(short_title("one two three four five six seven eight").split()) == 5
