"""
LLM integration — extracts structured data from listing text
and scores each listing against user-defined qualitative criteria.
Supports any provider that litellm supports (Anthropic, OpenAI, Gemini, Groq, Ollama, Mistral, …).
"""

import json
import re
from typing import Callable, Optional

MAX_LISTINGS_PER_BATCH = 5
MAX_TEXT_PER_LISTING = 6000  # chars sent to LLM per listing
MAX_FILTER_BATCH = 10        # listings per relevance-filter call


def _call_llm(
    model: str,
    prompt: str,
    api_key: str = "",
    base_url: str = "",
    max_tokens: int = 2048,
    retries: int = 3,
) -> str:
    """Make an LLM call via litellm, retrying after 60s on rate limit errors."""
    import litellm
    import time
    litellm.suppress_debug_info = True

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url

    for attempt in range(retries):
        try:
            response = litellm.completion(**kwargs)
            return response.choices[0].message.content
        except Exception as exc:
            msg = str(exc).lower()
            is_rate_limit = any(p in msg for p in ("rate limit", "429", "too many requests", "overloaded"))
            if is_rate_limit and attempt < retries - 1:
                wait = 60
                print(f"[LLM] Rate limited — waiting {wait}s before retry {attempt + 2}/{retries}...")
                time.sleep(wait)
            else:
                raise


def parse_json_response(text: str) -> object:
    """Extract and parse the first JSON object or array from an LLM response.
    Handles markdown code fences (```json ... ```).
    Raises ValueError if no valid JSON is found.
    """
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No valid JSON found in response: {text[:200]}")


def _build_extraction_prompt(batch: list[dict]) -> str:
    parts = []
    for i, listing in enumerate(batch, 1):
        snippet = listing.get("body") or ""
        page = listing.get("page_text") or ""
        # Always include the DDG snippet — it often has price/location in the first sentence.
        # Prepend it to the scraped page text so the LLM sees both sources.
        if snippet and page:
            text_source = f"[Search snippet]: {snippet}\n[Page text]: {page}"
        else:
            text_source = snippet or page
        text_source = text_source[:MAX_TEXT_PER_LISTING]
        confidence = "high" if listing.get("scraped") else "low"
        parts.append(
            f"Listing {i}:\n"
            f"Title: {listing.get('title', '')}\n"
            f"URL: {listing.get('href', '')}\n"
            f"Source confidence hint: {confidence}\n"
            f"Text:\n{text_source}\n"
        )

    listings_block = "\n---\n".join(parts)
    n = len(batch)
    return f"""You are extracting structured apartment listing data. Return ONLY a JSON array with exactly {n} objects.

Rules:
- Use null for any field not clearly stated in the text
- Do NOT guess or invent information
- price_monthly should be a number (monthly USD), null if not found
- bedrooms: 0 for studio, integer, null if unknown
- extraction_confidence: "high" if full page text provided, "medium" if partial, "low" if snippet only
- address: MUST be a real street address (e.g. "123 Main St, Denver, CO 80203") — do NOT use the listing title, description text, or any non-address string; use null if no real address is found
- apartment_name: branded name of the complex/building if mentioned (e.g. "Lux96", "The Meadows at Oak Park"), null if not found

If the text clearly shows a SEARCH RESULTS PAGE or LIST PAGE (multiple apartments, pagination, "X results found", etc.):
- Extract data for the FIRST / MOST PROMINENT individual unit described
- Set extraction_confidence to "low"
- Do NOT blend data from multiple units

Each object must have these exact keys:
  apartment_name, address, price_monthly, bedrooms, bathrooms, sqft, available_date, summary, extraction_confidence

{listings_block}

Return ONLY the JSON array, no explanation."""


def _build_scoring_prompt(listing: dict, criteria: list[dict]) -> str:
    snippet = listing.get("body") or ""
    page = listing.get("page_text") or ""
    if snippet and page:
        text = f"[Search snippet]: {snippet}\n[Page text]: {page}"
    else:
        text = snippet or page
    text = text[:MAX_TEXT_PER_LISTING]
    summary = listing.get("extracted", {}).get("summary", "")

    criteria_lines = "\n".join(
        f'{i+1}. "{c["text"]}" (user importance: {c["weight"]}/10)'
        for i, c in enumerate(criteria)
    )

    return f"""You are scoring an apartment listing against a renter's priorities.

Scoring scale:
- 0: Not mentioned at all
- 3: Vaguely implied
- 5: Likely but not confirmed
- 8: Strongly implied
- 10: Explicitly confirmed

IMPORTANT: A score of 0 means no evidence — do NOT assume positive attributes not mentioned.

Apartment summary: {summary}
Full listing text:
{text}

Criteria to score:
{criteria_lines}

Return ONLY this JSON (no explanation):
{{
  "overall_summary": "<2-3 sentence summary of this apartment for a renter>",
  "scores": [
    {{"criterion": "<criterion text>", "score": <0-10>, "note": "<max 15 words explaining the score>"}}
  ]
}}"""


def _extract_batch(
    model: str, api_key: str, base_url: str, batch: list[dict]
) -> list[dict]:
    """Extract structured fields from a batch of listings via a single LLM call.
    Falls back to individual calls if the batch response is malformed.
    """
    prompt = _build_extraction_prompt(batch)
    try:
        raw = _call_llm(model, prompt, api_key, base_url, max_tokens=2048)
        data = parse_json_response(raw)
        if isinstance(data, list) and len(data) == len(batch):
            return data
        raise ValueError(f"Expected {len(batch)} items, got {len(data) if isinstance(data, list) else type(data)}")
    except Exception:  # noqa: BLE001
        # Fall back: call individually
        results = []
        for item in batch:
            try:
                single_prompt = _build_extraction_prompt([item])
                raw = _call_llm(model, single_prompt, api_key, base_url, max_tokens=512)
                parsed = parse_json_response(raw)
                if isinstance(parsed, list) and parsed:
                    results.append(parsed[0])
                else:
                    results.append(_empty_extraction())
            except Exception:  # noqa: BLE001
                results.append(_empty_extraction())
        return results


def _empty_extraction() -> dict:
    return {
        "apartment_name": None,
        "address": None,
        "price_monthly": None,
        "bedrooms": None,
        "bathrooms": None,
        "sqft": None,
        "available_date": None,
        "summary": None,
        "extraction_confidence": "failed",
    }


def _score_listing(
    model: str, api_key: str, base_url: str, listing: dict, criteria: list[dict]
) -> dict:
    """Score a single listing's qualitative criteria."""
    if not criteria:
        return {"scores": [], "overall_summary": listing.get("extracted", {}).get("summary", "")}

    prompt = _build_scoring_prompt(listing, criteria)
    try:
        raw = _call_llm(model, prompt, api_key, base_url, max_tokens=2048)
        return parse_json_response(raw)
    except Exception:  # noqa: BLE001
        return {
            "scores": [
                {"criterion": c["text"], "score": None, "note": "scoring failed"}
                for c in criteria
            ],
            "overall_summary": "",
        }


def _build_filter_prompt(
    batch: list[dict],
    city: str,
    min_price: int,
    max_price: int,
    min_beds: int,
    max_beds: int,
) -> str:
    parts = []
    for i, listing in enumerate(batch, 1):
        text = (listing.get("page_text") or listing.get("body") or "")[:800]
        parts.append(
            f"Listing {i}:\n"
            f"Title: {listing.get('title', '')}\n"
            f"URL: {listing.get('href', '')}\n"
            f"Text: {text}\n"
        )
    listings_block = "\n---\n".join(parts)
    n = len(batch)
    if min_beds == 0 and max_beds == 0:
        beds_desc = "studio"
    elif min_beds == max_beds:
        beds_desc = f"{min_beds} bedroom"
    else:
        beds_desc = f"{min_beds}–{max_beds} bedrooms"

    return f"""You are a filter for an apartment search tool. Determine if each listing is a relevant long-term rental.

Search criteria:
- City/area: {city or 'anywhere in the US'}
- Price: ${min_price}–${max_price}/month
- Bedrooms: {beds_desc}

Mark a listing RELEVANT if it appears to be a long-term residential rental (month-to-month or annual lease) that:
1. Is in or near the target city/area (or the location is unclear from the text)
2. Is plausibly within the price range (or price is not mentioned)

Mark a listing IRRELEVANT only if it is clearly:
- A vacation/short-term/nightly rental (Airbnb, VRBO, hotel, etc.)
- A property for sale (not for rent)
- In the wrong country or a clearly different city/region
- Not a residential rental at all (news article, forum post, advertisement, etc.)
- Clearly outside the price range (e.g. $10,000/mo when searching $1,000–$2,000)

When in doubt, mark RELEVANT.

{listings_block}

Return ONLY a JSON array of exactly {n} objects:
[{{"idx": 1, "relevant": true}}, {{"idx": 2, "relevant": false}}, ...]"""


def filter_irrelevant_listings(
    listings: list[dict],
    city: str,
    min_price: int,
    max_price: int,
    min_beds: int,
    max_beds: int,
    api_key: str,
    model: str,
    base_url: str = "",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """Drop obviously irrelevant listings before extraction/scoring.

    Uses a fast batch LLM call per group of listings to check whether each
    is a long-term rental in the right location/price range.  Falls back to
    returning the full input list on any error so the pipeline never stalls.
    """
    if not api_key or not model or not listings:
        return listings

    kept: list[dict] = []
    total = len(listings)

    for batch_start in range(0, total, MAX_FILTER_BATCH):
        batch = listings[batch_start: batch_start + MAX_FILTER_BATCH]
        if progress_callback:
            frac = 0.56 + (batch_start / max(total, 1)) * 0.04
            progress_callback(
                frac,
                f"Checking relevance of listings {batch_start + 1}–"
                f"{batch_start + len(batch)} of {total}...",
            )
        try:
            prompt = _build_filter_prompt(batch, city, min_price, max_price, min_beds, max_beds)
            raw = _call_llm(model, prompt, api_key, base_url, max_tokens=512)
            data = parse_json_response(raw)
            if isinstance(data, list) and len(data) == len(batch):
                for listing, item in zip(batch, data):
                    if not isinstance(item, dict) or item.get("relevant") is not False:
                        kept.append(listing)
            else:
                kept.extend(batch)  # malformed response — keep all
        except Exception:  # noqa: BLE001
            kept.extend(batch)  # any error — keep all

    # Never return an empty list; fall back to the full input
    return kept if kept else listings


def analyze_listings_batch(
    listings: list[dict],
    criteria: list[dict],
    api_key: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    model: str = "claude-sonnet-4-6",
    base_url: str = "",
) -> list[dict]:
    """Main analysis entry point.

    1. Batch-extract structured fields (5 listings per call)
    2. Score each listing's qualitative criteria (1 call per listing)
    3. Attach 'extracted' and 'scoring' dicts to each listing

    Returns the enriched listings list.
    """
    total = len(listings)
    provider_label = model.split("/")[0] if "/" in model else "AI"

    # Phase 1: extraction
    for batch_start in range(0, total, MAX_LISTINGS_PER_BATCH):
        batch = listings[batch_start: batch_start + MAX_LISTINGS_PER_BATCH]
        if progress_callback:
            frac = 0.6 + (batch_start / max(total, 1)) * 0.15
            progress_callback(
                frac,
                f"Extracting listing data {batch_start + 1}–{batch_start + len(batch)} of {total}...",
            )
        extracted_list = _extract_batch(model, api_key, base_url, batch)
        for listing, extracted in zip(batch, extracted_list):
            listing["extracted"] = extracted

    # Phase 2: criteria scoring
    for i, listing in enumerate(listings):
        if progress_callback:
            frac = 0.75 + (i / max(total, 1)) * 0.23
            progress_callback(
                frac,
                f"Scoring listing {i + 1} of {total} with {provider_label}...",
            )
        conf = listing.get("extracted", {}).get("extraction_confidence", "failed")
        if conf == "failed":
            listing["scoring"] = {
                "scores": [
                    {"criterion": c["text"], "score": None, "note": "insufficient listing data"}
                    for c in criteria
                ],
                "overall_summary": "Could not extract sufficient data from this listing.",
            }
        else:
            listing["scoring"] = _score_listing(model, api_key, base_url, listing, criteria)

    if progress_callback:
        progress_callback(0.98, "Analysis complete.")

    return listings
