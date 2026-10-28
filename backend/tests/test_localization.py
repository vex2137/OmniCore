import pytest

from omnicore.localization import catalog, negotiate_locale
from omnicore.schemas import Locale


def test_catalogs_have_identical_keys_and_nonempty_values(client):
    assert client.get("/api/v1/locales").json() == ["en-US", "pl-PL"]
    english = client.get("/api/v1/locales/en-US").json()["messages"]
    polish = client.get("/api/v1/locales/pl-PL").json()["messages"]
    assert english.keys() == polish.keys()
    assert all(isinstance(v, str) and v.strip() for v in [*english.values(), *polish.values()])
    assert polish["nav.chat"] == "Czat"
    assert english["nav.chat"] == "Chat"
    assert english == catalog(Locale.EN)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, Locale.EN),
        ("pl", Locale.PL),
        ("pl-PL,en-US;q=0.5", Locale.PL),
        ("en;q=0.9,pl;q=1", Locale.PL),
        ("fr,pl;q=0.4", Locale.PL),
        ("pl;q=0,en", Locale.EN),
        ("pl;q=bad,en", Locale.EN),
        ("fr", Locale.EN),
    ],
)
def test_language_negotiation(header, expected):
    assert negotiate_locale(header) == expected


def test_switch_language_without_restart(client):
    for locale in ["pl-PL", "en-US"]:
        assert client.put("/api/v1/settings", json={"locale": locale}).status_code == 200
        assert client.get("/api/v1/settings").json()["locale"] == locale
        assert client.get(f"/api/v1/locales/{locale}").status_code == 200
    assert client.get("/api/v1/locales/../../etc/passwd").status_code == 404
    assert client.get("/api/v1/locales/de-DE").status_code == 422
