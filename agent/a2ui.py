"""A2UI v0.8 payload helpers for Gemini Enterprise.

Gemini Enterprise renders A2UI v0.8 only, and expects each A2UI message as an
A2A *DataPart* (structured JSON) with metadata {"mimeType": "application/json+a2ui"}
— NOT as a file/blob attachment ("Unsupported attachment" otherwise).

ADK convention for emitting a custom A2A DataPart from agent code: wrap the
DataPart JSON in <a2a_datapart_json>...</a2a_datapart_json> inside a text/plain
inline_data blob. ADK's part converter (google.adk.a2a.converters.part_converter)
unwraps it into a real DataPart on the A2A wire.

v0.8 message sequence per response (one DataPart each):
    1. surfaceUpdate    — flat list of components, referenced by id
    2. dataModelUpdate  — data model (empty for static buttons)
    3. beginRendering   — signals client to render from the root component
"""
import json
import uuid

from google.genai import types as genai_types

A2UI_MIME_TYPE = "application/json+a2ui"
_TAG_START = b"<a2a_datapart_json>"
_TAG_END = b"</a2a_datapart_json>"

# Note: beginRendering.styles (primaryColor / font per the v0.8 standard
# catalog) was tested and is NOT honored by the GE renderer — GE enforces
# its own theme. No styling control is available from the payload.
def _begin_rendering(surface_id: str) -> dict:
    return {"beginRendering": {"surfaceId": surface_id, "root": "root"}}


def followup_messages(prompt: str, buttons: list[dict]) -> list[dict]:
    """Builds the A2UI v0.8 message sequence for a prompt + follow-up buttons.

    A fresh surfaceId is generated on every call: the GE chat keys rendered
    cards by surfaceId, so reusing one makes later responses update the first
    card instead of rendering a new one (buttons would appear only once per
    conversation).

    Args:
        prompt: Text shown above the buttons.
        buttons: List of {"label": str, "action": str} dicts.
                 label  – button caption
                 action – follow-up question reported back via userAction
    """
    surface_id = f"followup-buttons-{uuid.uuid4().hex[:12]}"
    components = [
        {
            "id": "root",
            "component": {"Card": {"child": "content"}},
        },
        {
            "id": "content",
            "component": {
                "Column": {
                    "children": {
                        "explicitList": ["prompt_text"]
                        + [f"btn_{i}" for i in range(len(buttons))]
                    }
                }
            },
        },
        {
            "id": "prompt_text",
            "component": {"Text": {"text": {"literalString": prompt}}},
        },
    ]

    for i, b in enumerate(buttons):
        components.append(
            {
                "id": f"btn_{i}",
                "component": {
                    "Button": {
                        "child": f"btn_{i}_label",
                        "action": {
                            # Note: the GE client always shows "User action
                            # triggered." for button clicks regardless of this
                            # name (tested) — the readable transcript comes
                            # from the agent echoing context.question as a
                            # quote at the top of its reply.
                            "name": "followup_question",
                            "context": [
                                {
                                    "key": "question",
                                    "value": {"literalString": b["action"]},
                                }
                            ],
                        },
                    }
                },
            }
        )
        components.append(
            {
                "id": f"btn_{i}_label",
                "component": {"Text": {"text": {"literalString": b["label"]}}},
            }
        )

    return [
        {"surfaceUpdate": {"surfaceId": surface_id, "components": components}},
        {"dataModelUpdate": {"surfaceId": surface_id, "contents": {}}},
        _begin_rendering(surface_id),
    ]


def extract_user_action(content) -> dict | None:
    """Extracts a userAction event from incoming user content, if present.

    GE sends button clicks as an A2A DataPart; ADK converts it to a tagged
    text/plain inline_data blob (same convention as outgoing parts). Returns
    the userAction dict ({"name", "surfaceId", "context", ...}) or None.
    """
    if not content or not content.parts:
        return None
    for p in content.parts:
        data = None
        if (
            p.inline_data
            and p.inline_data.mime_type == "text/plain"
            and p.inline_data.data
            and p.inline_data.data.startswith(_TAG_START)
        ):
            raw = p.inline_data.data[len(_TAG_START):-len(_TAG_END)]
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
        elif p.text and "userAction" in p.text:
            try:
                data = json.loads(p.text)
            except ValueError:
                continue
        if not data:
            continue
        # DataPart shape: {"kind": "data", "data": {"userAction": {...}}}
        ua = data.get("data", data).get("userAction")
        if ua:
            return ua
    return None


def clicked_card_replacement(surface_id: str, question: str) -> list[dict]:
    """Rewrites an already-rendered button card to show the chosen question.

    GE shows a fixed "User action triggered." bubble for clicks (not
    controllable from the payload). As mitigation, this updates the clicked
    surface in place — the buttons disappear and the card shows which
    question was selected, making the transcript self-explanatory.
    """
    return [
        {
            "surfaceUpdate": {
                "surfaceId": surface_id,
                "components": [
                    {
                        "id": "root",
                        "component": {
                            "Text": {
                                "text": {"literalString": f"🗨️ {question}"}
                            }
                        },
                    }
                ],
            }
        },
    ]


def _ref_text(comp_id: str, index: int, ref: dict) -> dict:
    """One reference row as markdown link text (GE renders markdown in Text)."""
    return {
        "id": comp_id,
        "component": {
            "Text": {
                "text": {
                    "literalString": f"**{index + 1}.** [{ref['title']}]({ref['url']})"
                }
            }
        },
    }


def references_modal(
    references: list[dict],
    title: str | None = None,
    inline_count: int = 3,
) -> list[dict]:
    """Builds an A2UI v0.8 message sequence for references: top N inline,
    the full list behind a Modal as a two-column grid.

    Inline part (always visible, compact):
        Sources:
        1. <link>   2. <link>   3. <link>
        📚 View all 10 references        ← Modal entry point

    Modal overlay: the complete list split into two Columns inside a Row —
    half the height of a single long column, no dividers (the columns
    provide the visual structure instead).

    Args:
        references: List of {"title": str, "url": str} dicts.
        title: Modal entry-point label; defaults to "View all N references".
        inline_count: How many references to show inline (0 = modal only).
    """
    surface_id = f"references-{uuid.uuid4().hex[:12]}"
    label = title or f"View all {len(references)} references"

    inline = references[:inline_count]
    # Two-column split of the FULL list (left column gets the extra item)
    half = (len(references) + 1) // 2

    components = [
        # ── Inline part: header + top N + modal entry point ──────────
        {
            "id": "root",
            "component": {
                "Column": {
                    "alignment": "start",
                    "children": {
                        "explicitList": ["inline_header"]
                        + [f"inline_ref_{i}" for i in range(len(inline))]
                        + ["modal"]
                    },
                }
            },
        },
        {
            "id": "inline_header",
            "component": {
                "Text": {"usageHint": "h5", "text": {"literalString": "Sources"}}
            },
        },
        # ── Modal: full list as two columns in a row ─────────────────
        {
            "id": "modal",
            "component": {
                "Modal": {
                    "entryPointChild": "entry_button",
                    "contentChild": "modal_card",
                }
            },
        },
        {
            "id": "entry_button",
            "component": {"Text": {"text": {"literalString": f"📚 {label}"}}},
        },
        {
            "id": "modal_card",
            "component": {"Card": {"child": "modal_content"}},
        },
        {
            "id": "modal_content",
            "component": {
                "Column": {
                    "alignment": "stretch",
                    "children": {"explicitList": ["modal_header", "columns_row"]},
                }
            },
        },
        {
            "id": "modal_header",
            "component": {
                "Text": {"usageHint": "h2", "text": {"literalString": "References"}}
            },
        },
        {
            "id": "columns_row",
            "component": {
                "Row": {
                    "alignment": "start",
                    "distribution": "spaceBetween",
                    "children": {"explicitList": ["col_left", "col_right"]},
                }
            },
        },
        {
            "id": "col_left",
            "component": {
                "Column": {
                    "alignment": "start",
                    "children": {
                        "explicitList": [f"modal_ref_{i}" for i in range(half)]
                    },
                }
            },
        },
        {
            "id": "col_right",
            "component": {
                "Column": {
                    "alignment": "start",
                    "children": {
                        "explicitList": [
                            f"modal_ref_{i}" for i in range(half, len(references))
                        ]
                    },
                }
            },
        },
    ]

    for i, ref in enumerate(inline):
        components.append(_ref_text(f"inline_ref_{i}", i, ref))
    for i, ref in enumerate(references):
        components.append(_ref_text(f"modal_ref_{i}", i, ref))

    return [
        {"surfaceUpdate": {"surfaceId": surface_id, "components": components}},
        {"dataModelUpdate": {"surfaceId": surface_id, "contents": {}}},
        _begin_rendering(surface_id),
    ]


def to_genai_part(a2ui_message: dict) -> genai_types.Part:
    """Wraps one A2UI message so ADK emits it as an A2A DataPart.

    Produces the tagged text/plain blob that ADK's part converter unwraps
    into: DataPart(data=<a2ui_message>, metadata={"mimeType": A2UI_MIME_TYPE}).
    """
    data_part_json = json.dumps(
        {
            "kind": "data",
            "data": a2ui_message,
            "metadata": {"mimeType": A2UI_MIME_TYPE},
        }
    )
    return genai_types.Part(
        inline_data=genai_types.Blob(
            mime_type="text/plain",
            data=_TAG_START + data_part_json.encode("utf-8") + _TAG_END,
        )
    )


# ── Static follow-up set used by the demo agent ────────────────────────────
# Must be a function (not a module-level constant): each call generates a
# fresh surfaceId so every response renders its own button card in GE.
def demo_followups() -> list[dict]:
    return followup_messages(
        prompt="What would you like to explore next?",
        buttons=[
            {"label": "Tell me more",       "action": "Can you tell me more about that?"},
            {"label": "Give an example",    "action": "Can you give me a concrete example?"},
            {"label": "Summarize",          "action": "Please summarize the key points in bullet form"},
            {"label": "Why does it matter?", "action": "Why does this matter in a real-world context?"},
        ],
    )
