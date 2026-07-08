"""AI Business Advisor: turns the real computed opportunity factors for a
location into narrative advice via the Gemini API.

This is explicitly advisory, not predictive - it explains and contextualizes
scores that were already computed by the opportunity model, it does not
generate its own scores or claim to know how a business will perform. If
GEMINI_API_KEY isn't configured, the endpoint returns a clear "unavailable"
response rather than fabricating advice from a template.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import ServerError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash-lite"
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0

SYSTEM_INSTRUCTION = """You are a location-strategy advisor for small business owners in Kigali, \
Rwanda. You are given real, already-computed spatial data about one candidate location: demand, \
accessibility, commercial activity, competition, and welfare/affordability signals, plus the \
business category being considered.

Write concise, practical advice grounded ONLY in the numbers given to you. Do not invent facts \
about the location, do not claim to know competitor names or exact foot traffic, and do not \
predict revenue, profit, or whether the business will succeed - that is explicitly out of scope. \
Frame everything as considerations to weigh, not guarantees.

Cover, briefly: (1) what the numbers suggest about who the likely customers are and when they'd \
visit, (2) a positioning idea suited to the demand/competition balance shown (e.g. differentiate \
vs. compete on price, given the competition level), (3) one or two practical next steps specific \
to this category and this data. Keep it to 4-6 short sentences, plain language, no headers or \
markdown, no bullet lists - written prose."""

SYSTEM_INSTRUCTION_RW = SYSTEM_INSTRUCTION + """

Write your entire response in Kinyarwanda, natural and clear for a Kigali small business owner, \
not a literal machine translation. Do not include any English in the response."""

FOLLOW_UP_INSTRUCTION = """

The conversation may continue with follow-up questions about this same location. Keep answering \
grounded ONLY in the numbers already given to you above and anything you've already said in this \
conversation - do not invent new facts (rent, named competitors, exact foot traffic, and so on) \
to answer a question just because it was asked. If a follow-up asks about something not covered \
by the data (e.g. actual rent prices, specific competitor identities), say plainly that it isn't \
something this data covers and suggest it as a field-check item instead of guessing. Keep replies \
short - a few sentences, plain prose, no headers or bullet lists."""

MAX_HISTORY_MESSAGES = 20


def _client() -> genai.Client | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    return genai.Client(api_key=settings.gemini_api_key)


def is_available() -> bool:
    return _client() is not None


def generate_advice(assessment: dict[str, Any], locale: str | None = None, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """assessment is the payload returned by ml_opportunity_service.assess_location_ml().

    history, if given, is the prior conversation for this same location as a list
    of {"role": "user"|"assistant", "text": str}, ending with the newest user
    question still awaiting a reply. Empty/omitted history produces the original
    single-shot initial advice. Conversation state lives entirely on the client -
    it's resent in full on every follow-up rather than persisted server-side,
    since a location assessment session doesn't need to survive a page reload.
    """
    client = _client()
    if client is None:
        return {
            "available": False,
            "message": "The AI Business Advisor is not configured on this deployment. "
                       "Set GEMINI_API_KEY to enable it.",
            "advice": None,
        }

    is_follow_up = bool(history)
    system_instruction = SYSTEM_INSTRUCTION_RW if (locale or "").lower().startswith(("rw", "kin")) else SYSTEM_INSTRUCTION
    if is_follow_up:
        system_instruction += FOLLOW_UP_INSTRUCTION

    overall = assessment.get("overall", {})
    factors = assessment.get("factors", {})
    competition = assessment.get("competition", {})

    context_prompt = (
        f"Business category: {assessment.get('business_category')}\n"
        f"Location: {assessment.get('sector') or 'unknown sector'}, {assessment.get('district') or 'unknown district'}\n"
        f"Opportunity index score (0-100, higher is better): {overall.get('opportunity_score')}\n"
        f"Opportunity classification: {overall.get('opportunity_type')}\n"
        f"Confidence in this assessment (0-100): {overall.get('confidence_score')}\n"
        f"Demand score: {factors.get('demand_score')}\n"
        f"Accessibility score: {factors.get('accessibility_score')}\n"
        f"Commercial activity score: {factors.get('commercial_activity_score')}\n"
        f"Competition pressure (0-100, higher means more competitors): {factors.get('competition_pressure')}\n"
        f"Same-category competitors within 300m/500m/1000m: "
        f"{competition.get('within_300m')}/{competition.get('within_500m')}/{competition.get('within_1000m')}"
    )

    contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=context_prompt)])]
    for msg in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        text = str(msg.get("text") or "").strip()
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.4,
                    max_output_tokens=400,
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Empty response from Gemini")
            return {"available": True, "message": None, "advice": text, "model": MODEL_NAME}
        except ServerError as exc:
            # Transient overload (503) - worth one retry before giving up.
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)
        except Exception as exc:
            last_error = exc
            break

    logger.warning("AI advisor generation failed after %d attempt(s): %s", MAX_ATTEMPTS, last_error)
    return {
        "available": False,
        "message": "The AI Business Advisor could not generate advice right now. Please try again shortly.",
        "advice": None,
    }
