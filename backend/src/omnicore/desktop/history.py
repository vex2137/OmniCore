"""Disjoint history groups in the user's local calendar."""

from datetime import datetime

GROUPS = ("pinned", "today", "yesterday", "last_week", "last_month", "older")


def grouped_history(records, now=None):
    now = now or datetime.now().astimezone()
    groups = {key: [] for key in GROUPS}
    for record in sorted(records, key=lambda r: r.get("updated_at", ""), reverse=True):
        try:
            day = datetime.fromisoformat(record["updated_at"]).astimezone(now.tzinfo).date()
            age = max(0, (now.date() - day).days)
        except (ValueError, KeyError, TypeError):
            age = 31
        key = (
            "today"
            if age == 0
            else "yesterday"
            if age == 1
            else "last_week"
            if age < 7
            else "last_month"
            if age < 30
            else "older"
        )
        groups["pinned" if record.get("pinned") else key].append(record)
    return groups
