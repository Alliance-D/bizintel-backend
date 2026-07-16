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
Rwanda. You are given a real, model-based demand-versus-supply gap analysis for one candidate \
location: how many businesses of this category the area's fundamentals (population, income, \
transport, nearby anchors) predict, versus how many are actually observed nearby, plus \
demand/accessibility/commercial-activity signals and the business category being considered.

This is a spatial gap measurement, not a success predictor. A positive gap means fundamentals \
predict more businesses than are currently there (underserved); near zero means supply already \
matches what's predicted (balanced); negative means more supply than predicted (saturated). It \
cannot see businesses OpenStreetMap never mapped, especially informal ones, so treat "observed" as \
a floor, not a ceiling.

Write concise, practical advice grounded ONLY in the numbers given to you. Do not invent facts \
about the location, do not claim to know competitor names or exact foot traffic, and do not \
predict revenue, profit, or whether the business will succeed - that is explicitly out of scope. \
Frame everything as considerations to weigh, not guarantees.

Cover, briefly: (1) what the expected-versus-observed gap suggests about this location for this \
category - if there is room, say plainly that the area looks able to support more than it has; \
(2) WHY, tied to the concrete signals given - the people living nearby, the commercial activity, \
and especially the foot-traffic anchors (bus stops, markets, schools pull a steady stream of \
people past a storefront, which a walk-in business depends on); (3) what to look for on the \
ground when picking an actual unit - things like choosing a spot close to the main road for \
visibility and access, or near a bus stop or the market where foot traffic is heaviest; (4) one \
or two things to verify in person, since OSM undercounts informal businesses. Keep it to 4-7 \
short sentences, plain language, no headers or markdown, no bullet lists - written prose.

You may also be given optional user-stated context (a rent/budget figure, free-text notes). Use \
it only to personalize tone and practical framing - e.g. whether a positioning idea fits a tight \
budget. Never invent specific numbers (exact rent prices, revenue) from it, and never treat it as \
data the model used to compute the gap - it did not."""

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
    """Construct a Gemini client, or None when no API key is configured."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    return genai.Client(api_key=settings.gemini_api_key)


def is_available() -> bool:
    """True when the AI advisor is configured on this deployment."""
    return _client() is not None


def build_context_prompt(assessment: dict[str, Any], user_context: dict[str, str] | None = None) -> str:
    """Pure function (no Gemini call) so the prompt content is unit-testable."""
    overall = assessment.get("overall", {})
    factors = assessment.get("factors", {})
    competition = assessment.get("competition", {})
    signals = assessment.get("signals", {})

    location = assessment.get("location_label") or f"{assessment.get('sector') or 'unknown sector'}, {assessment.get('district') or 'unknown district'}"
    lines = [
        f"Business category: {assessment.get('business_category')}",
        f"Location: {location}",
        f"Expected number of {assessment.get('business_category')} businesses nearby, predicted from area fundamentals: {overall.get('expected_count')}",
        f"Observed number of {assessment.get('business_category')} businesses actually nearby (OSM-derived, likely undercounts informal ones): {overall.get('observed_count')}",
        f"Gap (expected minus observed, positive = underserved, negative = saturated): {overall.get('gap')}",
        f"Classification: {overall.get('opportunity_type')}",
        f"Viability (model probability that the area's fundamentals support this category at all, 0-1): {overall.get('viability')}",
        f"Confidence in this assessment (0-100): {overall.get('confidence_score')}",
        f"People living nearby (approx within 1km): {signals.get('people_within_1km')}",
        f"Commercial activity level in the area: {signals.get('commercial_activity_level')}",
        f"Foot-traffic anchors within 1km - bus stops: {signals.get('bus_stop_count_500m')} (nearest {signals.get('nearest_bus_stop_m')}m), "
        f"schools: {signals.get('school_count_1000m')}, health facilities: {signals.get('health_facility_count_1000m')}, "
        f"distance to nearest market: {signals.get('market_distance_m')}m",
        f"Same-category competitors within 300m/500m/1000m: "
        f"{competition.get('within_300m')}/{competition.get('within_500m')}/{competition.get('within_1000m')}",
    ]

    budget = (user_context or {}).get("budget")
    notes = (user_context or {}).get("notes")
    if budget:
        lines.append(f"User-stated rent/budget context: {budget}")
    if notes:
        lines.append(f"User-stated other context: {notes}")
    if budget or notes:
        lines.append(
            "Use the user-stated context above only to personalize tone and practical framing - "
            "never invent specific numbers (e.g. exact rent prices) from it, and never treat it as "
            "data the model used."
        )
    return "\n".join(lines)


def generate_advice(
    assessment: dict[str, Any], locale: str | None = None,
    history: list[dict[str, str]] | None = None, user_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """assessment is the payload returned by ml_opportunity_service.assess_location_ml().

    history, if given, is the prior conversation for this same location as a list
    of {"role": "user"|"assistant", "text": str}, ending with the newest user
    question still awaiting a reply. Empty/omitted history produces the original
    single-shot initial advice. Conversation state lives entirely on the client -
    it's resent in full on every follow-up rather than persisted server-side,
    since a location assessment session doesn't need to survive a page reload.

    user_context, if given, is optional user-stated {"budget": str, "notes": str} -
    passed through to Gemini for personalized framing only, never fed to the model.
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

    context_prompt = build_context_prompt(assessment, user_context)

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
