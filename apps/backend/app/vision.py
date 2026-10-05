"""Best-effort check that a submitted photo actually shows a gas meter (Gemini vision).

This is a fraud/mistake filter, not a security boundary: the admin still reads the
number off the photo and visually confirms it during review. If the check itself
cannot run (no API key configured, network error, unexpected response), the photo
is allowed through rather than blocking gas meter reporting.
"""
import base64
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("app.vision")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
PROMPT = (
    "You check photos submitted by residents reporting a gas meter reading. "
    "Reply with exactly one word: METER if the photo clearly shows a physical gas "
    "consumption meter with a visible numeric display, or NOT_METER for anything else "
    "(other objects, screenshots, blurry or unrecognizable images, unrelated photos)."
)


async def looks_like_gas_meter(image_bytes: bytes) -> bool | None:
    """True/False when the check ran; None when it could not be performed."""
    key = get_settings().gemini_api_key
    if not key:
        return None
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode()}},
                {"text": PROMPT},
            ],
        }],
        # thinkingBudget: 0 keeps this cheap and deterministic for a one-word classification;
        # maxOutputTokens must stay generous even so, or the model's internal reasoning
        # tokens alone can exhaust the budget and truncate the visible answer.
        "generationConfig": {"maxOutputTokens": 200, "temperature": 0, "thinkingConfig": {"thinkingBudget": 0}},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(GEMINI_URL, params={"key": key}, json=body)
            response.raise_for_status()
            data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
        return text.startswith("METER")
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("Gemini meter-photo check unavailable: %s", exc)
        return None
