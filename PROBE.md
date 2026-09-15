# Probe: slides from the repo + slider navigation in GE chat

A narrower first step than [ge-chat-spike.md](ge-chat-spike.md): **no storage at all.**
Slides are synthetic (`ppt_gen_v3/templates/demo/library.pdf`), rasterised into
`agent/assets/` by `make_assets.py`, bundled with the agent and sent as `data:` URIs.

Questions:

1. Does GE render an `Image` whose URL is a `data:` URI on **v0.9**? (Failed on v0.8.)
2. Can a **Slider** change what is shown **client-side**, i.e. with no round trip and no
   "User action triggered." bubble? Needs data binding and `formatString`, neither verified in GE.
3. Fallback: do **Tabs** give no-round-trip navigation across slides?

## Run it (office project)

```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt   # Python 3.13 is fine — concierge deployed from 3.13.5
copy env.dev.example .env.dev    # fill in the office project + staging bucket
gcloud auth application-default login   # the office account
.venv\Scripts\python deploy_to_agent_engine.py
```

Register in GE: Admin console → Agents → Add agent → Vertex AI Agent Engine → paste the
`projects/.../reasoningEngines/...` name printed by the deploy. Assets are already built
in `agent/assets/` (not yet committed) and ship inside the agent package; rerun `make_assets.py` only if the library changes.

Offline tests: `.venv\Scripts\python -m pytest tests -q`

## Order to test in GE chat

Type one trigger per message. Judge **only in GE chat** (the Playground shows raw JSON).
Keep **F12 → Console** open; copy any `Refused to load the image … img-src …` line verbatim.

| # | type | look for | depends on |
|---|---|---|---|
| 0 | `help` | card with the trigger list renders | — (if not, stop) |
| 1 | `img-data-tiny` | a small slide thumbnail | — |
| 2 | `img-data` | slide 1 at full card width | — **the gate** |
| 3 | `slider-bind` | number under the slider follows the drag | — |
| 4 | `slider-text` | "Slide N of 5" updates live while dragging | — |
| 5 | `slider-gstatic` | photo changes as the slider moves; no "User action triggered." | 4 |
| 6 | `tabs-deck` | 9 tabs, each shows its slide | 2 |
| 7 | `slider-deck` | slide changes as the slider moves (nested `${/s${/page}}` lookup — a long shot) | 2 + 5 |

For the sliders also note: does the value snap to whole numbers, or send `3.4`-style decimals
(which would break `…/3.4.jpg`)?

## Results log — fill in as you go

| probe | result | exact error / observation |
|---|---|---|
| `help` renders | | |
| `img-data-tiny` | | |
| `img-data` | | |
| Console `img-src` line, if any | | |
| `slider-bind` | | |
| `slider-text` (formatString) | | |
| slider value: integers or decimals? | | |
| `slider-gstatic` | | |
| `tabs-deck` | | |
| `slider-deck` | | |

## What the results mean

| outcome | design |
|---|---|
| `img-data` ✅ + `slider-deck` ✅ | Target design works with no storage: slides travel in the message, slider navigates locally. Watch payload size for 60 slides (~15–20 KB each at 800 px here). |
| `img-data` ✅ + `slider-gstatic` ✅ + `slider-deck` ❌ | Slider can drive an image, but not by picking a `data:` URI. Use **Tabs** with `data:` URIs now, or a slider over hosted URLs once storage is in (→ spike T1). |
| `img-data` ✅ + sliders ❌ | Navigation = **Tabs** (or a vertical Column of slides / Modal). |
| `img-data` ❌ | Repo-only preview is not possible. Slides must be hosted → run spike T1 (signed URLs). `slider-gstatic` still tells us whether the slider design works then. |
