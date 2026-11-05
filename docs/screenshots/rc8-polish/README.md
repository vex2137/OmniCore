# RC8 UI stabilization — cloud evidence and local checks

All PNGs are actual Qt offscreen captures, not generated artwork. `matrix.json`
records 96 samples: chat, local models, Hugging Face, transfers, settings and
 diagnostics at 1280×720, 1366×768, 1920×1080 and 2560×1440, each at 80%, 100%,
125% and 150%. Window dimensions matched every requested logical size; visible
buttons were checked against their minimum text size, and history kept useful
vertical space. Committed PNGs cover every view/resolution at 100%, plus the
smallest window at 150%, selected scale examples and compact mode. Remaining
captures can be reproduced with the test command below.

The matrix uses tiny, unverified GGUF metadata fixtures and manually seeded
conversation content. It does not claim inference support for those fixtures.
`real-*.png` and `theme-*.png` render the existing isolated SmolLM2 CPU test history
from the earlier RC8 session, not a new GPU inference run. Empty Hugging Face and
transfer states were tested without downloading any weights. Long catalog/history
measurements are presentation construction times on this Cloud host, not an
end-to-end API or hardware performance promise.

## What was fixed

- Large history insertion previously blocked in `QListWidget.addItem` and was
  interrupted after 98 seconds. Batched layout and suspended painting reduced
  measured construction of 5000 rows to about 0.20 seconds in the final sample.
- Compact header/collapse control, draggable 200–360 px sidebar, 52 px compact
  mode, width field in appearance settings, compact search/refresh. Rename,
  pin and confirmed deletion remain in the conversation context menu.
- Long names elide with full tooltips. First group rows no longer paint duplicate
  titles. Model headers fit text; secondary model actions are in the menu and
  full paths are available in the detail tooltip.
- Empty transfers show guidance rather than a meaningless zero-percent progress
  bar. Existing transfer controls appear when there is a selected real record.
- Assistant footer icons have accessible names and tooltips, including native
  reload fallback for regeneration and a toggle for the actual statistics.
- Logical text/control scale 80–150% persists independently of screen DPI. Qt
  applies device pixel ratio; application code never changes `QT_SCALE_FACTOR`.
  In a separate process with DPR=2, 150% produced a 21-logical-pixel body font,
  not 42. Branding and action icon sizes stay bounded.
- Palette text and adapted text/focus accents were checked for 4.5:1 contrast;
  button text chooses the stronger black/white contrast against the actual fill.
  Native keyboard focus and Ctrl+F from compact mode were exercised.

## Reproduce cloud checks

```sh
uv sync --frozen --extra desktop --group gui-test
QT_QPA_PLATFORM=offscreen OMNICORE_STABILITY_OUTPUT=/tmp/omnicore-layout \
  uv run --group gui-test pytest desktop/tests/test_stabilization.py -q
QT_QPA_PLATFORM=offscreen uv run --group gui-test pytest backend/tests desktop/tests -q
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 OMNICORE_EXPECT_DPR=2 \
  uv run --group gui-test pytest \
  desktop/tests/test_stabilization.py::test_external_dpr_does_not_rescale_logical_fonts -q
```

## Still required on CachyOS

From this branch's checkout, run `uv sync --frozen --extra desktop`, then
`uv run omnicore-desktop`. No AppImage or APK was built in this session.
The inherited distribution version was not bumped or released.

1. KDE Plasma native Wayland and X11/XWayland: fonts, icons, tooltips, clipboard,
   file dialogs, keyboard context menu and focus, window resizing/maximization.
   Use the default platform selection first. Test explicit `QT_QPA_PLATFORM=wayland`
   or `xcb` only where that platform is installed and available.
2. KDE display scaling (including fractional scaling and moving between monitors)
   together with app 80/100/125/150%. Do not add an extra environment scale factor
   merely to compensate for an already scaled desktop.
3. Existing user history, pins, collapsed sections, themes, model roots, context
   settings and favorites must survive restart and source/app updates without reset.
4. Load the owner's LFM3 and Qwen GGUF models; check CPU/Auto/CUDA selection,
   actual RTX 4060 offload, streaming, cancellation, earlier-answer regeneration
   and process cleanup when closing during generation.
5. Check the real desktop accessibility integration/screen reader. Offscreen
   contrast calculations and keyboard tests do not certify assistive technology.

No native CachyOS compositor, physical RTX 4060, Android phone or release signature
was verified by these Cloud UI checks. No release/tag was created.
