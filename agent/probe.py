"""Probe cards — each trigger answers one question about slide preview in GE chat.

No storage: slides are JPEGs bundled in agent/assets/ and sent as data: URIs.
Every surface gets a fresh surfaceId, and every question gets its own surface, so a
payload that blanks one card cannot hide a pass in another.
"""
import base64
import uuid
from pathlib import Path

CATALOG_BASIC = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
ASSETS = Path(__file__).parent / "assets"
GSTATIC = "https://www.gstatic.com/webp/gallery"  # 1.jpg … 5.jpg exist (checked)
GSTATIC_COUNT = 5


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


def _card(name: str, title: str, note: str, body: list[dict], data_model: dict | None = None,
          nested: list[dict] = ()) -> list[dict]:
    """Card > Column > [h4 title, body note, *body]. `nested` = components referenced by id
    from inside `body` (e.g. tab contents), so not direct children of the column."""
    comps = [
        {"id": "root", "component": "Card", "child": "col"},
        {"id": "col", "component": "Column", "align": "stretch",
         "children": ["title", "note"] + [c["id"] for c in body]},
        _text("title", title, "h4"),
        _text("note", note),
        *body,
        *nested,
    ]
    return _surface(name, comps, data_model)


# ── probes ───────────────────────────────────────────────────────────────────

TRIGGERS = {
    "help": "this list",
    "img-data-tiny": "one 160 px slide as a data: URI (a few KB)",
    "img-data": "one 800 px slide as a data: URI — the gate",
    "slider-bind": "Slider + Text bound to the same path — does the text follow the slider?",
    "slider-text": "Slider + formatString Text — does ${/page} interpolate live?",
    "slider-gstatic": "Slider drives an Image URL via formatString (hosted gstatic images 1–5)",
    "tabs-deck": "all slides as data: URIs, one per tab — navigation with no round trip",
    "slider-deck": "Slider picks a data: URI slide from the data model — the target design",
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


BUILDERS = {
    "help": help_card,
    "img-data-tiny": img_data_tiny,
    "img-data": img_data,
    "slider-bind": slider_bind,
    "slider-text": slider_text,
    "slider-gstatic": slider_gstatic,
    "tabs-deck": tabs_deck,
    "slider-deck": slider_deck,
}


def cards_for(text: str) -> tuple[str, list[dict]]:
    """Exact trigger match (trimmed, case-insensitive). Unknown text → help."""
    key = (text or "").strip().lower()
    if key in BUILDERS:
        return key, BUILDERS[key]()
    return "help", help_card()
