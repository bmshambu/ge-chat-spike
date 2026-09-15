"""Deck preview probe for Gemini Enterprise (A2UI v0.9, basic catalog).

Deterministic: the after_model_callback matches the user's typed text exactly against
probe.TRIGGERS and appends that probe's cards. The model's reply is replaced with one
line naming the probe. No model judgement anywhere in the path.
"""
import json
import re

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types

from . import probe
from .a2ui import to_genai_part

_TAG_START = b"<a2a_datapart_json>"
_TAG_END = b"</a2a_datapart_json>"

# A2UI message keys to strip from history so the model can't echo them (and so megabytes
# of data: URIs from earlier probes don't get resent to the model every turn).
_A2UI_KEYS = ("createSurface", "updateComponents", "updateDataModel", "deleteSurface")
_ECHO_RE = re.compile(
    r"<a2a_datapart_json>.*?</a2a_datapart_json>"
    r'|\{\s*"(?:version|createSurface|updateComponents|updateDataModel)"\s*:.*',
    re.DOTALL,
)


def _is_a2ui_part(part) -> bool:
    blob = getattr(part, "inline_data", None)
    if blob and blob.data and blob.data.startswith(_TAG_START):
        try:
            d = json.loads(blob.data[len(_TAG_START):-len(_TAG_END)])
        except (ValueError, UnicodeDecodeError):
            return False
        inner = d.get("data", d)
        return isinstance(inner, dict) and any(k in inner for k in _A2UI_KEYS)
    return bool(part.text and any(f'"{k}"' in part.text for k in _A2UI_KEYS))


def _strip_history(callback_context: CallbackContext, llm_request: LlmRequest):
    for cnt in llm_request.contents:
        if cnt.parts:
            kept = [p for p in cnt.parts if not _is_a2ui_part(p)]
            if len(kept) != len(cnt.parts):
                cnt.parts = kept
    return None


def _current_user_content(callback_context):
    uc = getattr(callback_context, "user_content", None)
    if uc is not None:
        return uc
    try:
        for event in reversed(callback_context.session.events):
            if getattr(event, "author", None) == "user" and event.content:
                return event.content
    except Exception:
        pass
    return None


def _user_text(content) -> str:
    if not content or not getattr(content, "parts", None):
        return ""
    return " ".join(p.text for p in content.parts if getattr(p, "text", None))


def _append_probe(callback_context: CallbackContext, llm_response: LlmResponse):
    if llm_response.partial:
        return None
    content = llm_response.content
    if not content or not content.parts:
        return None
    if any(p.function_call for p in content.parts if p.function_call):
        return None

    trigger = probe.normalize(_user_text(_current_user_content(callback_context)))
    if trigger in probe.EVENT_BUILDERS:
        # Multi-event probe: only the first chunk rides on this event; FollowUpEvents sends the rest.
        name, messages = trigger, probe.event_chunks(trigger, callback_context.invocation_id)[0]
    else:
        name, messages = probe.cards_for(trigger)

    # Model text is irrelevant: drop it and lead with one line naming the probe.
    content.parts = [genai_types.Part(text=f"Probe: **{name}**")]
    content.parts += [to_genai_part(m) for m in messages]
    return llm_response


class FollowUpEvents(BaseAgent):
    """Runs after the LLM agent in the same turn. For multi-event probes, yields the remaining
    chunks as separate events (same surfaceId, derived from the invocation id). Otherwise silent."""

    async def _run_async_impl(self, ctx: InvocationContext):
        trigger = probe.normalize(_user_text(ctx.user_content))
        if trigger not in probe.EVENT_BUILDERS:
            return
        for chunk in probe.event_chunks(trigger, ctx.invocation_id)[1:]:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=genai_types.Content(role="model", parts=[to_genai_part(m) for m in chunk]),
            )


probe_agent = LlmAgent(
    name="deck_preview_probe_agent",
    model="gemini-2.5-flash",
    instruction="Reply with exactly one short line naming the test that was run. Never output JSON.",
    before_model_callback=_strip_history,
    after_model_callback=_append_probe,
)

root_agent = SequentialAgent(
    name="deck_preview_probe",
    sub_agents=[probe_agent, FollowUpEvents(name="probe_follow_up_events")],
)
