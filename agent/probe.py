"""Probe cards — each trigger answers one question about slide preview in GE chat.

No storage: slides are JPEGs bundled in agent/assets/ and sent as data: URIs.
Every surface gets a fresh surfaceId, and every question gets its own surface, so a
payload that blanks one card cannot hide a pass in another.
"""
import base64
import hashlib
import json
import math
import uuid
from pathlib import Path

CATALOG_BASIC = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
ASSETS = Path(__file__).parent / "assets"
GSTATIC = "https://www.gstatic.com/webp/gallery"  # 1.jpg … 5.jpg exist (checked)
GSTATIC_COUNT = 5
SIZE_PROBES_KB = (600, 900, 1200)  # round 4: 900 KB part rendered, 1.2 MB part dropped
REPLY_PROBES_MB = (3, 6, 12)       # round 5: is there a whole-reply ceiling?
PART_KB = 500                      # per-DataPart budget for chunked probes (limit ~1 MB)
EVENT_KB = 2500                    # round 6: per-event budget (3.4 MB reply ✅, 6.3 MB → 400)


# ── assets ───────────────────────────────────────────────────────────────────

def slide_files() -> list[Path]:
    return sorted(ASSETS.glob("slide-*.jpg"))


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


# ── component + message helpers ──────────────────────────────────────────────

def _fmt(template: str) -> dict:
    """Client-side formatString — ${/path} is interpolated by the renderer."""
    return {"call": "formatString", "args": {"value": template}, "returnType": "string"}


def _text(cid, text, variant="body"):
    return {"id": cid, "component": "Text", "text": text, "variant": variant}


def _image(cid, url):
    return {"id": cid, "component": "Image", "url": url, "fit": "contain", "variant": "largeFeature"}


def _slider(cid, path, mn, mx, label):
    return {"id": cid, "component": "Slider", "label": label, "value": {"path": path}, "min": mn, "max": mx}


def _surface(name: str, components: list[dict], data_model: dict | None = None) -> list[dict]:
    sid = f"{name}-{uuid.uuid4().hex[:12]}"
    msgs = [
        {"version": "v0.9", "createSurface": {"surfaceId": sid, "catalogId": CATALOG_BASIC, "sendDataModel": False}},
        {"version": "v0.9", "updateComponents": {"surfaceId": sid, "components": components}},
    ]
    if data_model is not None:
        msgs.append({"version": "v0.9", "updateDataModel": {"surfaceId": sid, "path": "/", "value": data_model}})
    return msgs


def _card_head(title: str, note: str, body: list[dict]) -> list[dict]:
    """Card > Column > [h4 title, body note, *body]."""
    return [
        {"id": "root", "component": "Card", "child": "col"},
        {"id": "col", "component": "Column", "align": "stretch",
         "children": ["title", "note"] + [c["id"] for c in body]},
        _text("title", title, "h4"),
        _text("note", note),
        *body,
    ]


def _card(name: str, title: str, note: str, body: list[dict], data_model: dict | None = None,
          nested: list[dict] = ()) -> list[dict]:
    """`nested` = components referenced by id from inside `body` (e.g. tab contents),
    so not direct children of the column."""
    return _surface(name, [*_card_head(title, note, body), *nested], data_model)


# ── probes ───────────────────────────────────────────────────────────────────

TRIGGERS = {
    "help": "this list",
    "img-data-tiny": "one 160 px slide as a data: URI (a few KB)",
    "img-data": "one 800 px slide as a data: URI — the gate",
    "slider-bind": "Slider + Text bound to the same path — does the text follow the slider?",
    "slider-text": "Slider + formatString Text — does ${/page} interpolate live?",
    "slider-gstatic": "Slider drives an Image URL via formatString (hosted gstatic images 1–5)",
    "tabs-deck": "all slides as data: URIs, one per tab — navigation with no round trip",
    "slider-deck": "Slider picks a data: URI slide from the data model — ❌ in GE (no dynamic paths)",
    "chips-deck": "numbered chips; Image = formatString of the selection — ❌ in GE (no image)",
    "chips-deck-bind": "numbered chips; Image url bound straight to the selection — ✅ in GE",
    "thumbs-modal": "3×3 thumbnail grid; tap a thumbnail to open that slide in a Modal — ✅ in GE",
    "thumbs-modal-60": "60 thumbnails in one grid — ❌ in GE (card dropped, ~1.7 MB)",
    "tabs-thumbs-60": "60 thumbnails in tabs of 12 — ❌ in GE (card dropped, ~1.7 MB)",
    "chips-deck-60": "60 chips switching one slide — ❌ in GE (card dropped, ~1.4 MB)",
    **{f"size-{kb}": f"one part padded to ~{kb} KB" + (" — ❌ in GE" if kb > 900 else " — ✅ in GE")
       for kb in SIZE_PROBES_KB},
    "split-60": "60 thumbnails, one card, ≤ 175 KB parts — ✅ in GE (limit is per part)",
    "surfaces-60": "60 thumbnails as 5 cards of 12 in one reply — ✅ in GE",
    **{f"reply-{mb}mb": f"one card, ~{mb} MB reply in one event" + (" — ✅ in GE" if mb <= 3 else " — ❌ 400 in GE")
       for mb in REPLY_PROBES_MB},
    "heavy-60": "60 photo slides at 1200 px (~16 MB) in one event — ❌ 400 in GE",
    "events-6mb": "~6 MB for one card spread over events of ≤ 2.5 MB — is the limit per event?",
    "events-12mb": "~12 MB, same, over ~5 events",
    "heavy-60-events": "60 photo slides at 1200 px (~16 MB) over ~7 events",
}


def help_card() -> list[dict]:
    lines = "\n".join(f"- **{k}** — {v}" for k, v in TRIGGERS.items())
    return _card("help", "Deck preview probe",
                 "Type one trigger word per message. Judge each card on its own.",
                 [_text("list", lines)])


def img_data_tiny() -> list[dict]:
    return _card("img-data-tiny", "img-data-tiny", "160 px PNG sent as a data: URI.",
                 [_image("img", data_uri(ASSETS / "tiny.png"))])


def img_data() -> list[dict]:
    first = slide_files()[0]
    kb = first.stat().st_size * 4 / 3 / 1024
    return _card("img-data", "img-data", f"Slide 1, 800 px JPEG, ~{kb:.0f} KB as base64.",
                 [_image("img", data_uri(first))])


def slider_bind() -> list[dict]:
    return _card("slider-bind", "slider-bind",
                 "Drag the slider. The number below should follow it (plain path binding, no formatString).",
                 [_slider("slider", "/page", 1, GSTATIC_COUNT, "Page"),
                  {"id": "value", "component": "Text", "text": {"path": "/page"}, "variant": "h5"}],
                 {"page": 1})


def slider_text() -> list[dict]:
    return _card("slider-text", "slider-text",
                 "Drag the slider. The line below should read 'Slide N of 5' and update live.",
                 [_slider("slider", "/page", 1, GSTATIC_COUNT, "Page"),
                  {"id": "value", "component": "Text", "text": _fmt("Slide ${/page} of " + str(GSTATIC_COUNT)),
                   "variant": "h5"}],
                 {"page": 1})


def slider_gstatic() -> list[dict]:
    return _card("slider-gstatic", "slider-gstatic",
                 "Drag the slider. The photo should change (URL built client-side from /page).",
                 [_slider("slider", "/page", 1, GSTATIC_COUNT, "Photo"),
                  {"id": "value", "component": "Text", "text": _fmt("Photo ${/page}"), "variant": "caption"},
                  _image("img", _fmt(GSTATIC + "/${/page}.jpg"))],
                 {"page": 1})


def tabs_deck() -> list[dict]:
    files = slide_files()
    body = [{"id": "tabs", "component": "Tabs",
             "tabs": [{"title": str(i), "child": f"s{i}"} for i in range(1, len(files) + 1)]}]
    slides = [_image(f"s{i}", data_uri(f)) for i, f in enumerate(files, start=1)]
    return _card("tabs-deck", "tabs-deck", f"{len(files)} slides, one per tab. Click through the tabs.",
                 body, nested=slides)


def slider_deck() -> list[dict]:
    files = slide_files()
    model = {"page": 1, **{f"s{i}": data_uri(f) for i, f in enumerate(files, start=1)}}
    return _card("slider-deck", "slider-deck",
                 f"Drag the slider through {len(files)} slides. Image URL = ${{/s${{/page}}}} (nested lookup).",
                 [_slider("slider", "/page", 1, len(files), "Slide"),
                  {"id": "value", "component": "Text", "text": _fmt("Slide ${/page} of " + str(len(files))),
                   "variant": "caption"},
                  _image("img", _fmt("${/s${/page}}"))],
                 model)


def _chips_deck(name: str, url: dict, how: str, files: list[Path] | None = None) -> list[dict]:
    """The slider can't choose a data-model path, but a ChoicePicker writes its option VALUE.
    So each chip's value is the slide's data: URI, and the Image reads the selection back."""
    uris = [data_uri(f) for f in (files or slide_files())]
    return _card(name, name, f"Tap a number. The slide below should switch with no round trip ({how}). "
                             f"{len(uris)} slides, ~{_kb(uris)} KB of images.",
                 [{"id": "pager", "component": "ChoicePicker", "label": "Slide", "variant": "mutuallyExclusive",
                   "displayStyle": "chips", "value": {"path": "/current"},
                   "options": [{"label": str(i), "value": u} for i, u in enumerate(uris, start=1)]},
                  _image("img", url)],
                 {"current": [uris[0]]})


def chips_deck() -> list[dict]:
    # /current is a one-item string array; formatString should stringify it to the URI itself.
    return _chips_deck("chips-deck", _fmt("${/current}"), "url = formatString ${/current}")


def chips_deck_bind() -> list[dict]:
    return _chips_deck("chips-deck-bind", {"path": "/current"}, "url bound to /current")


def _kb(uris) -> int:
    return round(sum(len(u) for u in uris) / 1024)


def _thumb_grid(items: list[tuple[int, str, str]], total: int, per_row: int = 3) -> tuple[list[dict], list[dict]]:
    """items = (slide number, thumbnail uri, full uri). Returns (Row components, everything they reference).
    Each thumbnail is the trigger of a Modal whose content is the full slide."""
    rows, nested = [], []
    for r in range(0, len(items), per_row):
        chunk = items[r:r + per_row]
        rows.append({"id": f"row{chunk[0][0]}", "component": "Row", "align": "center", "justify": "start",
                     "children": [f"m{n}" for n, _, _ in chunk]})
    for n, thumb, full in items:
        nested += [
            {"id": f"m{n}", "component": "Modal", "trigger": f"t{n}", "content": f"c{n}", "weight": 1},
            {**_image(f"t{n}", thumb), "variant": "smallFeature"},
            {"id": f"c{n}", "component": "Column", "align": "stretch", "children": [f"ch{n}", f"ci{n}"]},
            _text(f"ch{n}", f"Slide {n} of {total}", "h5"),
            _image(f"ci{n}", full),
        ]
    return rows, nested


def thumbs_modal() -> list[dict]:
    uris = [data_uri(f) for f in slide_files()]
    rows, nested = _thumb_grid([(i, u, u) for i, u in enumerate(uris, start=1)], len(uris))
    return _card("thumbs-modal", "thumbs-modal", "Tap a thumbnail to open that slide.", rows, nested=nested)


# ── 60-slide scale tests (assets/deck60, each slide stamped "N / 60") ─────────

DECK60 = ASSETS / "deck60"
HEAVY60 = ASSETS / "heavy60"


def _deck_items(folder: Path) -> list[tuple[int, str, str]]:
    slides = sorted(folder.glob("slide-*.jpg"))
    thumbs = sorted(folder.glob("thumb-*.jpg"))
    return [(n, data_uri(t), data_uri(s)) for n, (t, s) in enumerate(zip(thumbs, slides), start=1)]


def deck60_items() -> list[tuple[int, str, str]]:
    return _deck_items(DECK60)


def thumbs_modal_60() -> list[dict]:
    items = deck60_items()
    rows, nested = _thumb_grid(items, len(items))
    kb = _kb([t for _, t, _ in items] + [s for _, _, s in items])
    return _card("thumbs-modal-60", "thumbs-modal-60",
                 f"{len(items)} thumbnails in one grid, each opens its slide. ~{kb} KB of images.",
                 rows, nested=nested)


def tabs_thumbs_60(per_tab: int = 12) -> list[dict]:
    """Thumbnail grid split into tabs of 12 — the whole deck without one long wall."""
    items = deck60_items()
    tabs, nested = [], []
    for p in range(0, len(items), per_tab):
        chunk = items[p:p + per_tab]
        page_id = f"page{p // per_tab + 1}"
        rows, refs = _thumb_grid(chunk, len(items))
        tabs.append({"title": f"{chunk[0][0]}–{chunk[-1][0]}", "child": page_id})
        nested += [{"id": page_id, "component": "Column", "align": "stretch", "children": [r["id"] for r in rows]},
                   *rows, *refs]
    kb = _kb([t for _, t, _ in items] + [s for _, _, s in items])
    return _card("tabs-thumbs-60", "tabs-thumbs-60",
                 f"{len(items)} slides, {per_tab} thumbnails per tab; tap one to open it. ~{kb} KB of images.",
                 [{"id": "tabs", "component": "Tabs", "tabs": tabs}], nested=nested)


def chips_deck_60() -> list[dict]:
    return _chips_deck("chips-deck-60", {"path": "/current"}, "url bound to /current",
                       files=sorted(DECK60.glob("slide-*.jpg")))


# ── Size ceiling (round 4) ───────────────────────────────────────────────────
# Round 3: every 60-slide reply (1.4–1.7 MB, one updateComponents part) dropped its card
# silently, while thumbs-modal (~400 KB) renders. These find where the limit sits and
# whether it applies per DataPart, per surface or per whole reply.

def _pack(groups: list[list[dict]], limit_kb: float) -> list[list[dict]]:
    """Greedily pack component groups (one group per slide) into parts of ≤ limit_kb of JSON.
    A group is never split; a single oversized group gets a part of its own."""
    parts, current, size = [], [], 0
    for group in groups:
        g = len(json.dumps(group))
        if current and size + g > limit_kb * 1024:
            parts.append(current)
            current, size = [], 0
        current += group
        size += g
    return parts + ([current] if current else [])


def size_probe(kb: int) -> list[dict]:
    """One small visible slide; the updateComponents part is padded to ~kb KB with invisible
    accessibility text, so size is tested apart from image count."""
    name = f"size-{kb}"
    img = {**_image("img", data_uri(ASSETS / "tiny.png")), "description": ""}
    msgs = _card(name, name, f"Single updateComponents part padded to ~{kb} KB. Renders = under the limit.",
                 [img])
    comps = msgs[1]["updateComponents"]["components"]
    comp = next(c for c in comps if c["id"] == "img")
    comp["description"] = "x" * max(0, kb * 1024 - len(json.dumps(msgs[1])))
    return msgs


def _split_thumbs(name: str, items: list[tuple[int, str, str]], part_kb: float, what: str,
                  sid: str | None = None) -> list[dict]:
    """A thumbnail-grid deck as ONE surface sent in many small updateComponents parts:
    slide components first (packed to ≤ part_kb), then the card skeleton that references them."""
    rows, nested = _thumb_grid(items, len(items))
    per_slide = len(nested) // len(items)
    parts = _pack([nested[i:i + per_slide] for i in range(0, len(nested), per_slide)], part_kb)
    total_kb = _kb([t for _, t, _ in items] + [s for _, _, s in items])
    head = _card_head(name, f"{len(items)} {what}, one card, sent in {len(parts) + 1} parts of ≤ ~{part_kb:.0f} KB "
                            f"(~{total_kb / 1024:.1f} MB of images). Tap a thumbnail to open it.", rows)
    sid = sid or f"{name}-{uuid.uuid4().hex[:12]}"
    msgs = [{"version": "v0.9", "createSurface": {"surfaceId": sid, "catalogId": CATALOG_BASIC,
                                                  "sendDataModel": False}}]
    msgs += [{"version": "v0.9", "updateComponents": {"surfaceId": sid, "components": p}} for p in [*parts, head]]
    return msgs


def split_60() -> list[dict]:
    """thumbs-modal-60 in ≤ ~175 KB parts (round 4 ✅)."""
    return _split_thumbs("split-60", deck60_items(), 175, "text slides")


def heavy_60(sid: str | None = None, name: str = "heavy-60") -> list[dict]:
    """60 photo-heavy 1200 px slides — the realistic worst case — chunked to PART_KB."""
    return _split_thumbs(name, _deck_items(HEAVY60), PART_KB, "photo slides at 1200 px", sid)


def reply_probe(mb: int, sid: str | None = None, name: str | None = None) -> list[dict]:
    """One card whose reply totals ~mb MB, every part ~PART_KB (safely under the per-part limit).
    Each part carries a visible 'part k of n' line plus invisible padding, so a missing part shows."""
    name = name or f"reply-{mb}mb"
    sid = sid or f"{name}-{uuid.uuid4().hex[:12]}"
    n = math.ceil(mb * 1024 / PART_KB)
    tiny = data_uri(ASSETS / "tiny.png")
    msgs = [{"version": "v0.9", "createSurface": {"surfaceId": sid, "catalogId": CATALOG_BASIC,
                                                  "sendDataModel": False}}]
    for k in range(1, n + 1):
        img = {**_image(f"i{k}", tiny), "variant": "icon", "description": ""}
        msg = {"version": "v0.9", "updateComponents": {"surfaceId": sid, "components": [
            {"id": f"r{k}", "component": "Row", "align": "center", "justify": "start", "children": [f"i{k}", f"l{k}"]},
            img,
            _text(f"l{k}", f"part {k} of {n} arrived", "caption"),
        ]}}
        img["description"] = "x" * max(0, PART_KB * 1024 - len(json.dumps(msg)))
        msgs.append(msg)
    head = _card_head(name, f"{n} parts of ~{PART_KB} KB (~{mb} MB reply). Every 'part k of {n}' line must show.", [])
    head[1]["children"] += [f"r{k}" for k in range(1, n + 1)]  # head[1] is the card's Column
    msgs.append({"version": "v0.9", "updateComponents": {"surfaceId": sid, "components": head}})
    return msgs


# ── Multi-event delivery (round 6) ───────────────────────────────────────────
# Round 5: a 3.4 MB reply renders, 6.3 MB / 12 MB / heavy-60 fail with a 400 "exceeded limit".
# All of those went out as ONE agent event. These send the same messages for ONE surface
# spread over several events in the same turn, each ≤ EVENT_KB: is the limit per event or per turn?
# The first chunk rides on the LLM agent's event; agent.FollowUpEvents yields the rest.

EVENT_BUILDERS = {
    "events-6mb": lambda sid: reply_probe(6, sid, "events-6mb"),
    "events-12mb": lambda sid: reply_probe(12, sid, "events-12mb"),
    "heavy-60-events": lambda sid: heavy_60(sid, "heavy-60-events"),
}


def sid_for(trigger: str, invocation_id: str) -> str:
    """Same surfaceId from both agents in the turn, without passing megabytes through state."""
    return f"{trigger}-{hashlib.sha1(invocation_id.encode()).hexdigest()[:12]}"


def event_chunks(trigger: str, invocation_id: str, limit_kb: float = EVENT_KB) -> list[list[dict]]:
    """The probe's messages packed into per-event chunks, in order (createSurface first, root last)."""
    msgs = EVENT_BUILDERS[trigger](sid_for(trigger, invocation_id))
    return _pack([[m] for m in msgs], limit_kb)


def surfaces_60(per_card: int = 12) -> list[dict]:
    """60 thumbnails as 5 separate cards of 12 (~330 KB each) in ONE reply."""
    items = deck60_items()
    msgs = []
    for k, p in enumerate(range(0, len(items), per_card), start=1):
        chunk = items[p:p + per_card]
        rows, nested = _thumb_grid(chunk, len(items))
        label = f"{chunk[0][0]}–{chunk[-1][0]}"
        msgs += _card(f"surfaces-60-{k}", f"surfaces-60 · {label}",
                      f"Card {k} of 5 in one reply. Tap a thumbnail to open it.", rows, nested=nested)
    return msgs


BUILDERS = {
    "help": help_card,
    "img-data-tiny": img_data_tiny,
    "img-data": img_data,
    "slider-bind": slider_bind,
    "slider-text": slider_text,
    "slider-gstatic": slider_gstatic,
    "tabs-deck": tabs_deck,
    "slider-deck": slider_deck,
    "chips-deck": chips_deck,
    "chips-deck-bind": chips_deck_bind,
    "thumbs-modal": thumbs_modal,
    "thumbs-modal-60": thumbs_modal_60,
    "tabs-thumbs-60": tabs_thumbs_60,
    "chips-deck-60": chips_deck_60,
    **{f"size-{kb}": (lambda kb=kb: size_probe(kb)) for kb in SIZE_PROBES_KB},
    "split-60": split_60,
    "surfaces-60": surfaces_60,
    **{f"reply-{mb}mb": (lambda mb=mb: reply_probe(mb)) for mb in REPLY_PROBES_MB},
    "heavy-60": heavy_60,
}


def normalize(text: str) -> str:
    return (text or "").strip().lower()


def cards_for(text: str) -> tuple[str, list[dict]]:
    """Exact trigger match (trimmed, case-insensitive). Unknown text → help."""
    key = normalize(text)
    if key in BUILDERS:
        return key, BUILDERS[key]()
    return "help", help_card()
