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
and committed in `agent/assets/` and ship inside the agent package; rerun `make_assets.py` only if the library changes.

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

**Round 2** (after `slider-deck` failed): `chips-deck`, `chips-deck-bind`, `thumbs-modal`.
For chips, check the slide switches on tap **without** a "User action triggered." bubble.
For the modal, check a thumbnail (not a button) opens it.

For the sliders also note: does the value snap to whole numbers, or send `3.4`-style decimals
(which would break `…/3.4.jpg`)?

## Results log — fill in as you go

| probe | result | exact error / observation |
|---|---|---|
Round 1 — office GE, 2026-09-15:

| probe | result | exact error / observation |
|---|---|---|
| `help` renders | ✅ | |
| `img-data-tiny` | ✅ | |
| `img-data` | ✅ | **`data:` URI images render on v0.9** (v0.8 block gone) |
| Console `img-src` line, if any | — | none needed, nothing blocked |
| `slider-bind` | ✅ | plain `{"path"}` binding follows the slider live |
| `slider-text` (formatString) | ✅ | `formatString` `${/page}` interpolates live in GE |
| slider value: integers or decimals? | integers | "Slide 9 of 9"; `slider-gstatic` URLs resolved |
| `slider-gstatic` | ✅ | Slider drives an Image URL client-side, no round trip |
| `tabs-deck` | ✅ | 9 tabs, each slide renders, switching is local (screenshot: tab 7) |
| `slider-deck` | ❌ | slider + "Slide 9 of 9" render; **image empty**, rest of card intact. Expected per schema: a `path` is a literal JSON Pointer, so `${/s${/page}}` can't build a path. Slider can't pick among stored slides. |

Round 2 — workarounds for slider-deck (office GE, 2026-09-15):

| probe | result | exact error / observation |
|---|---|---|
| `chips-deck` (formatString of selection) | ❌ | chips render and select (chip 3 blue), **no image** below. formatString of a string-array path doesn't yield a usable URL. |
| `chips-deck-bind` (url bound to selection) | ✅ | tap chip 4 → slide 4 "Our approach" shows, no round trip. **Bind Image url straight to the ChoicePicker path.** |
| `thumbs-modal` (thumbnail opens slide) | ✅ | an `Image` works as a Modal trigger; modal shows "Slide 1 of 9" full slide |

Slider ↔ thumbnails is **not possible** on the basic catalog: a Slider only writes a number, and
nothing can map a number to a stored slide, open a Modal, switch a Tab or scroll. Sliders stay
viable only over hosted, pattern-named URLs (`slider-gstatic`).

Round 3 — 60 slides (pending). Slides are stamped "N / 60" — check order, not just presence:

| probe | result | render time, order, size errors |
|---|---|---|
| `thumbs-modal-60` (one grid) | | |
| `tabs-thumbs-60` (tabs of 12) | | |
| `chips-deck-60` (60 chips, one slide) | | |

## What the results mean

**Round 1 verdict:** repo-only preview **works** (data URIs + Tabs). A Slider can drive an
image only when the URL follows a pattern (`…/slide-${/page}.jpg`), i.e. hosted images whose
one credential covers every slide — per-object signed URLs don't. Round 2 decides whether a
numbered pager (chips) or thumbnail grid gives slider-like navigation without hosting.

| outcome | design |
|---|---|
| `img-data` ✅ + `slider-deck` ✅ | Target design works with no storage: slides travel in the message, slider navigates locally. Watch payload size for 60 slides (~15–20 KB each at 800 px here). |
| `img-data` ✅ + `slider-gstatic` ✅ + `slider-deck` ❌ | Slider can drive an image, but not by picking a `data:` URI. Use **Tabs** with `data:` URIs now, or a slider over hosted URLs once storage is in (→ spike T1). |
| `img-data` ✅ + sliders ❌ | Navigation = **Tabs** (or a vertical Column of slides / Modal). |
| `img-data` ❌ | Repo-only preview is not possible. Slides must be hosted → run spike T1 (signed URLs). `slider-gstatic` still tells us whether the slider design works then. |
