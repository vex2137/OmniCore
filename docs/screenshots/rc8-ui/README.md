# RC8 — models, appearance and chat controls

These are actual Qt offscreen captures. `my-models.png` uses two tiny GGUF
metadata fixtures imported through the real API; they are not tested inference
models. `real-local-models.png` shows the existing SmolLM2 catalog entry and
`real-context-details.png` shows its previously saved real CPU generation.
No new GPU or model compatibility claim follows from these screenshots.

`appearance-settings.png` and `all-theme-previews.png` show the Ocean palette
and all seven native theme preview icons. The System option follows Qt's system
color scheme; its swatch illustrates the light system variant. The custom accent
uses a native color dialog, persists locally, and can be reset independently.

`collapsed-history.png` shows the real history group control. Collapsing stores
local presentation preferences without deleting or modifying conversation data.
`context-details-unavailable.png` demonstrates the explicit unavailable state.
Context details always describe the last inference request, not the full history.

Favorites, accent and collapsed groups are desktop preferences. Model context
settings remain per-model on the backend. Sorting by recent use consumes actual
`last_inference.at` metadata; unknown timestamps sort after known ones. Model
loading status is obtained asynchronously from the backend's applied context.

Assistant footers provide copy and regeneration. Regenerating an older answer
branches from the question preceding that answer, preserving later messages in
the original conversation. It does not rewrite the existing history.
