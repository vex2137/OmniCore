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
    for scale in (80, 100, 150):
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
