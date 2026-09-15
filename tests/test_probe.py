r"""Offline tests for the deck preview probe — no LLM/network/GCP.

Confirms payload shapes, trigger dispatch and the A2A DataPart round trip.
Whether GE renders it is answered only by deploying.

Run from ge_chat_spike/:  ..\..\a2ui_gallary\.venv\Scripts\python -m pytest tests -v
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part
from google.genai import types as genai_types

from agent import probe
from agent.a2ui import to_genai_part
from agent.agent import _append_probe


def _components(msgs):
    return next(m["updateComponents"]["components"] for m in msgs if "updateComponents" in m)


def _model(msgs):
    return next((m["updateDataModel"]["value"] for m in msgs if "updateDataModel" in m), None)


@pytest.mark.parametrize("trigger", list(probe.BUILDERS))
class TestEveryProbe:
    def test_v09_messages_and_roundtrip(self, trigger):
        msgs = probe.BUILDERS[trigger]()
        assert all(m["version"] == "v0.9" for m in msgs)
        assert msgs[0]["createSurface"]["catalogId"] == probe.CATALOG_BASIC
        assert all(convert_genai_part_to_a2a_part(to_genai_part(m)) for m in msgs)

    def test_every_referenced_id_exists_once(self, trigger):
        comps = _components(probe.BUILDERS[trigger]())
        ids = [c["id"] for c in comps]
        assert len(ids) == len(set(ids)) and "root" in ids
        refs = []
        for c in comps:
            refs += c.get("children", []) + ([c["child"]] if "child" in c else [])
            refs += [t["child"] for t in c.get("tabs", [])]
            refs += [c[k] for k in ("trigger", "content") if c["component"] == "Modal"]
        assert set(refs) <= set(ids)
        assert set(ids) - set(refs) == {"root"}  # nothing orphaned

    def test_fresh_surface_id_each_call(self, trigger):
        a = probe.BUILDERS[trigger]()[0]["createSurface"]["surfaceId"]
        b = probe.BUILDERS[trigger]()[0]["createSurface"]["surfaceId"]
        assert a != b and a.startswith(trigger)


def test_nine_slides_bundled():
    assert len(probe.slide_files()) == 9
    assert (probe.ASSETS / "tiny.png").exists()


def test_img_data_is_a_jpeg_data_uri():
    img = next(c for c in _components(probe.img_data()) if c["component"] == "Image")
    assert img["url"].startswith("data:image/jpeg;base64,") and img["fit"] == "contain"


def test_slider_binds_page_and_is_seeded():
    for build in (probe.slider_bind, probe.slider_text, probe.slider_gstatic, probe.slider_deck):
        msgs = build()
        slider = next(c for c in _components(msgs) if c["component"] == "Slider")
        assert slider["value"] == {"path": "/page"}  # flat single-segment path
        assert _model(msgs)["page"] == 1


def test_slider_gstatic_url_is_client_side_format():
    img = next(c for c in _components(probe.slider_gstatic()) if c["component"] == "Image")
    assert img["url"] == {"call": "formatString", "args": {"value": probe.GSTATIC + "/${/page}.jpg"},
                          "returnType": "string"}


def test_tabs_deck_one_image_per_tab():
    comps = {c["id"]: c for c in _components(probe.tabs_deck())}
    tabs = comps["tabs"]["tabs"]
    assert [t["title"] for t in tabs] == [str(i) for i in range(1, 10)]
    assert all(comps[t["child"]]["url"].startswith("data:image/jpeg") for t in tabs)


def test_slider_deck_model_holds_every_slide():
    model = _model(probe.slider_deck())
    assert all(model[f"s{i}"].startswith("data:image/jpeg") for i in range(1, 10))


@pytest.mark.parametrize("build", [probe.chips_deck, probe.chips_deck_bind])
def test_chips_deck_values_are_slides_and_seed_first(build):
    msgs = build()
    picker = next(c for c in _components(msgs) if c["component"] == "ChoicePicker")
    values = [o["value"] for o in picker["options"]]
    assert [o["label"] for o in picker["options"]] == [str(i) for i in range(1, 10)]
    assert all(v.startswith("data:image/jpeg") for v in values)
    assert picker["value"] == {"path": "/current"}  # flat path
    assert _model(msgs) == {"current": [values[0]]}  # string array, per schema


def test_thumbs_modal_nine_modals_each_opens_its_slide():
    comps = {c["id"]: c for c in _components(probe.thumbs_modal())}
    modals = [c for c in comps.values() if c["component"] == "Modal"]
    assert len(modals) == 9
    for i in range(1, 10):
        m = comps[f"m{i}"]
        assert comps[m["trigger"]]["url"] == comps[f"ci{i}"]["url"]
        assert f"m{i}" in comps[f"row{(i - 1) // 3 + 1}"]["children"]


@pytest.mark.parametrize("typed,expected", [
    ("help", "help"), ("  IMG-DATA \n", "img-data"), ("tabs-deck", "tabs-deck"),
    ("hello there", "help"), ("", "help"),
])
def test_trigger_matching(typed, expected):
    assert probe.cards_for(typed)[0] == expected


def _ctx(text):
    ctx = MagicMock()
    ctx.user_content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
    return ctx


def _resp(text="Some model chatter"):
    r = MagicMock()
    r.partial = False
    r.content = genai_types.Content(role="model", parts=[genai_types.Part(text=text)])
    return r


def test_callback_replaces_text_and_appends_cards():
    resp = _resp()
    _append_probe(_ctx("slider-gstatic"), resp)
    parts = resp.content.parts
    assert parts[0].text == "Probe: **slider-gstatic**"
    a2ui = [convert_genai_part_to_a2a_part(p) for p in parts[1:]]
    assert len(a2ui) == 3 and all("application/json+a2ui" in str(a.root.metadata) for a in a2ui)


def test_callback_ignores_partial_responses():
    resp = _resp()
    resp.partial = True
    assert _append_probe(_ctx("help"), resp) is None
    assert len(resp.content.parts) == 1
