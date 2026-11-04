from datetime import UTC, datetime, timedelta

from omnicore.desktop.history import grouped_history


def test_history_groups_are_disjoint_and_pins_are_not_duplicated():
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    records = [
        {"id": str(age), "updated_at": (now - timedelta(days=age)).isoformat()}
        for age in (0, 1, 2, 6, 7, 29, 30, 60)
    ]
    records[2]["pinned"] = True
    groups = grouped_history(records, now)
    assert [r["id"] for r in groups["pinned"]] == ["2"]
    assert [r["id"] for r in groups["today"]] == ["0"]
    assert [r["id"] for r in groups["yesterday"]] == ["1"]
    assert [r["id"] for r in groups["last_week"]] == ["6"]
    assert [r["id"] for r in groups["last_month"]] == ["7", "29"]
    assert [r["id"] for r in groups["older"]] == ["30", "60"]
    assert sum(map(len, groups.values())) == len(records)
