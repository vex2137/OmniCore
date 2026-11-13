"""Layout checks use real native widgets, never infer hardware/desktop support."""

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.themes import PALETTES, contrast_ratio, readable_accent


def test_palette_contrast():
    for colors in PALETTES.values():
        bg, panel, field, fg, muted, _ = colors
        assert min(contrast_ratio(fg, surface) for surface in (bg, panel, field)) >= 4.5
        assert contrast_ratio(muted, bg) >= 4.5
        for chosen in ("#000000", "#ffffff", "#24aabb", "#6957d9"):
            adjusted = readable_accent(chosen, fg, (bg, panel, field))
            assert min(contrast_ratio(adjusted, surface) for surface in (bg, panel, field)) >= 4.5


def test_scale_is_logical_and_survives_restart(desktop, tmp_path, monkeypatch):
    w = desktop
    monkeypatch.setenv("QT_SCALE_FACTOR", "2")
    for scale in (80, 100, 150, 100):
        w.ui_scale.setValue(scale)
        assert f"font: {round(14 * scale / 100)}px" in w.styleSheet()
        assert os.environ["QT_SCALE_FACTOR"] == "2"
    w.ui_scale.setValue(150)
    path = tmp_path / "prefs.json"
    w.config.save(path)
    assert DesktopConfig.load(path).ui_scale == 150


def test_major_views_resolution_and_scale_matrix(desktop, qtbot):
    w = desktop
    w.onboarding.hide()
    from test_desktop import fixture_gguf, request

    from omnicore.desktop.config import data_path

    for name in ("Model testowy z długą nazwą", "Drugi model"):
        path = data_path() / "models" / (name + ".gguf")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fixture_gguf())
        request(w, "POST", "/api/v1/text/models/import", {"path": str(path)})
    w.refresh_models()
    record = request(w, "POST", "/api/v1/text/conversations", {"title": "Rozmowa do oceny układu"})
    for role, content in (
        ("user", "Sprawdź układ przy dużym tekście."),
        (
            "assistant",
            "## Przykładowa historia\n\n- Pierwszy punkt\n- Drugi punkt\n\n"
            "```python\nprint('layout')\n```",
        ),
    ):
        request(
            w,
            "POST",
            f"/api/v1/text/conversations/{record['id']}/messages",
            {"role": role, "content": content},
        )
    w.refresh_conversations(record["id"])
    qtbot.waitUntil(lambda: len(w.messages) == 2 and len(w.models) == 2)
    output = os.environ.get("OMNICORE_STABILITY_OUTPUT")
    destination = Path(output) if output else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
    report = []
    views = (
        (0, None, "chat"),
        (1, 0, "models"),
        (1, 1, "hugging-face"),
        (1, 2, "transfers"),
        (2, None, "settings"),
        (3, None, "diagnostics"),
    )
    for scale in (80, 100, 125, 150):
        w.ui_scale.setValue(scale)
        for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
            for page, tab, name in views:
                w.navigate(page)
                if tab is not None:
                    w.model_tabs.setCurrentIndex(tab)
                w.resize(width, height)
                qtbot.wait(40)
                sample = {
                    "scale": scale,
                    "view": name,
                    "requested": [width, height],
                    "actual": [w.width(), w.height()],
                }
                report.append(sample)
                if destination:
                    w.grab().save(str(destination / f"{name}-{width}x{height}-{scale}.png"))
                assert w.width() == width and w.height() == height, sample
                assert w.conversation_list.height() >= 150, sample
                # Visible top-level action buttons must fit their text. Scrolled content
                # is checked through its native viewport rather than forced into the window.
                for button in w.findChildren(QPushButton):
                    if button.isVisible() and button.text() and not w.config.sidebar_compact:
                        assert button.width() >= button.minimumSizeHint().width(), (
                            sample,
                            button.text(),
                            button.width(),
                            button.minimumSizeHint().width(),
                        )
    if destination:
        w.navigate(0)
        w.toggle_sidebar()
        qtbot.wait(80)
        w.grab().save(str(destination / "compact-150.png"))
        (destination / "matrix.json").write_text(json.dumps(report, indent=2))


def test_large_histories_and_catalogs_remain_bounded(desktop, qtbot, monkeypatch):
    from datetime import UTC, datetime
    from time import perf_counter

    w = desktop
    # Synthetic catalog/history data exercise presentation only, never inference.
    monkeypatch.setattr(w.api, "request", lambda *args, **kwargs: None)
    w.models = [
        dict(
            id=str(i),
            backend="llama.cpp",
            name=f"Model {i:04d} — długi opis",
            size_bytes=i,
            compatibility="unverified",
            format="GGUF",
            location="/fixture",
            metadata={},
        )
        for i in range(1000)
    ]
    started = perf_counter()
    w.refresh_model_table()
    model_seconds = perf_counter() - started
    assert w.model_table.rowCount() == 1000
    w.model_sort.setCurrentIndex(w.model_sort.findData("sort_size"))
    assert w.model_table.item(0, 0).data(Qt.UserRole) == "999"
    w.model_search.setText("Model 0999")
    assert w.model_table.rowCount() == 1
    now = datetime.now(UTC).isoformat()
    w.conversations = [
        dict(id=str(i), title=f"Rozmowa {i}", updated_at=now, pinned=i < 10) for i in range(5000)
    ]
    started = perf_counter()
    w._fill_conversations()
    history_seconds = perf_counter() - started
    assert w.conversation_list.count() == 5000
    assert w.conversation_list.itemWidget(w.conversation_list.item(0)) is not None
    w.toggle_history_group("today")
    assert w.conversation_list.item(11).isHidden()
    messages = [dict(id=str(i), role="user", content=f"Message {i}") for i in range(10000)]
    w.transcript.set_messages(messages, w.tr)
    assert len(w.transcript.cards) == 60
    assert w.transcript.more.isVisible()
    w.navigate(1)
    qtbot.wait(60)
    w.model_search.setFocus()
    assert w.model_search.hasFocus()
    assert w.model_search.accessibleName()
    output = os.environ.get("OMNICORE_STABILITY_OUTPUT")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        Path(output, "large-catalog.json").write_text(
            json.dumps(
                {
                    "model_rows": 1000,
                    "history_rows": 5000,
                    "messages": 10000,
                    "rendered_messages": len(w.transcript.cards),
                    "model_seconds": model_seconds,
                    "history_seconds": history_seconds,
                },
                indent=2,
            )
        )


def test_external_dpr_does_not_rescale_logical_fonts(desktop):
    from PySide6.QtWidgets import QApplication

    w = desktop
    w.ui_scale.setValue(150)
    assert w.model_search.font().pixelSize() == 21
    expected = os.environ.get("OMNICORE_EXPECT_DPR")
    if expected:
        assert QApplication.primaryScreen().devicePixelRatio() == float(expected)
    output = os.environ.get("OMNICORE_STABILITY_OUTPUT")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        Path(output, "dpi.json").write_text(
            json.dumps(
                {
                    "screen_dpr": QApplication.primaryScreen().devicePixelRatio(),
                    "scale_percent": w.config.ui_scale,
                    "logical_font_pixels": w.model_search.font().pixelSize(),
                },
                indent=2,
            )
        )


def test_sidebar_and_transfer_empty_state(desktop, qtbot, tmp_path):
    w = desktop
    assert w.sidebar_toggle.width() <= 32
    assert w.sidebar_width.parentWidget() is not w.history_panel
    w.shell.moveSplitter(280, 1)
    qtbot.waitUntil(lambda: w.config.sidebar_width == w.sidebar.width())
    assert 200 <= w.sidebar.width() <= 360
    path = tmp_path / "prefs.json"
    w.config.save(path)
    assert DesktopConfig.load(path).sidebar_width == w.sidebar.width()
    w.downloads = []
    w._show_download_progress()
    assert not w.transfers_empty.isHidden()
    assert w.download_progress.isHidden() and w.download_list.isHidden()
    w.downloads = [{"id": "transfer", "state": "running", "percent": 42}]
    w.download_list.addItem("transfer", "transfer")
    w._show_download_progress()
    assert w.transfers_empty.isHidden()
    assert not w.download_progress.isHidden()
    assert w.download_progress.value() == 42


def test_keyboard_search_from_compact_mode(desktop, qtbot):
    w = desktop
    w.toggle_sidebar()
    assert w.config.sidebar_compact
    qtbot.keyClick(w, Qt.Key_F, Qt.ControlModifier)
    qtbot.waitUntil(lambda: w.history_search.hasFocus())
    assert not w.config.sidebar_compact
    qtbot.keyClick(w.history_search, Qt.Key_Tab)
    assert w.history_refresh.hasFocus()
    assert w.history_refresh.accessibleName()


def test_beta3_all_history_headers_fit_at_narrow_widths(desktop, qtbot):
    from datetime import UTC, datetime, timedelta

    w = desktop
    now = datetime.now(UTC)
    w.conversations = [
        {
            "id": str(index),
            "title": "Historia o długiej nazwie " * 4,
            "pinned": index == 0,
            "updated_at": (now - timedelta(days=age)).isoformat(),
        }
        for index, age in enumerate((0, 0, 1, 3, 10, 60))
    ]
    w.onboarding.hide()
    w.resize(1280, 720)
    for locale in ("pl-PL", "en-US"):
        w.language.setCurrentIndex(w.language.findData(locale))
        for scale in (80, 100, 125, 150):
            w.ui_scale.setValue(scale)
            for width in (200, 232):
                w.sidebar_width.setValue(width)
                w._fill_conversations()
                qtbot.wait(20)
                headings = w.conversation_list.findChildren(QPushButton, "historyHeading")
                assert len(headings) == 6
                for heading in headings:
                    assert " ".join(heading.text().split()) == "▾ " + heading.accessibleName()
                    for line in heading.text().splitlines():
                        assert (
                            heading.width() >= heading.fontMetrics().horizontalAdvance(line) + 4
                        ), (locale, scale, width, heading.text(), heading.width())
                    assert heading.height() >= (
                        len(heading.text().splitlines()) * heading.fontMetrics().lineSpacing() + 4
                    )
    output = os.environ.get("OMNICORE_STABILITY_OUTPUT")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        w.language.setCurrentIndex(w.language.findData("pl-PL"))
        qtbot.wait(80)
        w.grab().save(str(Path(output) / "history-groups-150.png"))


def test_beta3_compact_sidebar_scales_proportionally(desktop, qtbot):
    w = desktop
    w.resize(1280, 760)
    w.toggle_sidebar()
    assert w.config.sidebar_compact
    for scale in (80, 90, 100, 125, 150):
        w.ui_scale.setValue(scale)
        qtbot.wait(30)
        expected_sidebar = max(1, round(52 * scale / 100))
        expected_btn = max(1, round(32 * scale / 100))
        assert w.sidebar.width() == expected_sidebar
        if scale == 100:
            assert 52 <= w.sidebar.width() <= 60
            assert 32 <= w.sidebar_toggle.width() <= 36
        for btn in (w.sidebar_toggle, w.new_button, *w.nav):
            assert btn.isVisible()
            assert btn.width() == expected_btn and btn.height() == expected_btn
            assert btn.width() < w.sidebar.width()
            assert btn.width() >= btn.minimumSizeHint().width()
            assert btn.height() >= btn.minimumSizeHint().height()
