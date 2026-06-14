"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Groq chat model used by the LLM-backed tools.
_MODEL = "llama-3.3-70b-versatile"

# Words that carry no search signal — stripped before scoring listings.
_STOPWORDS = {
    "a", "an", "the", "for", "under", "with", "and", "or", "of", "in", "to",
    "my", "i", "im", "looking", "want", "need", "size", "price", "that",
    "this", "some", "really", "please", "find", "me", "on", "is", "are", "at",
    "whats", "out", "there", "how", "would", "style", "it", "around", "about",
}

# A listing whose size string contains any of these is treated as size-flexible
# and passes the size filter regardless of the requested size.
_FLEXIBLE_SIZE_MARKERS = (
    "one size", "oversized", "adjustable", "fits most", "fits oversized",
)


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into alphanumeric tokens."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _size_matches(listing_size: str, requested: str) -> bool:
    """
    True if a listing's size satisfies the requested size.

    A listing passes if it is size-flexible (one size / oversized / adjustable)
    or if the requested size appears as a discrete token in its size string
    (so "M" matches "S/M" and "M/L" but not "US 9").
    """
    ls = listing_size.lower()
    if any(marker in ls for marker in _FLEXIBLE_SIZE_MARKERS):
        return True
    return requested.lower() in set(_tokenize(ls))


def _relevance_score(listing: dict, query_tokens: list[str]) -> int:
    """
    Score a listing against the query tokens. A token found in style_tags is
    worth 2 points; a token found in the title/description/category/colors is
    worth 1. Each token is counted once (tags take precedence).
    """
    tag_tokens = {t for tag in listing["style_tags"] for t in _tokenize(tag)}
    other_tokens: set[str] = set()
    other_tokens.update(_tokenize(listing["title"]))
    other_tokens.update(_tokenize(listing["description"]))
    other_tokens.update(_tokenize(listing["category"]))
    for color in listing["colors"]:
        other_tokens.update(_tokenize(color))

    score = 0
    for token in query_tokens:
        if token in tag_tokens:
            score += 2
        elif token in other_tokens:
            score += 1
    return score


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    query_tokens = [t for t in _tokenize(description) if t not in _STOPWORDS]

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and not _size_matches(listing["size"], size):
            continue
        score = _relevance_score(listing, query_tokens)
        if score == 0:
            continue
        scored.append((score, listing))

    # Highest score first; original order preserved for ties (stable sort).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    items = (wardrobe or {}).get("items", [])

    title = new_item.get("title", "this piece")
    category = new_item.get("category", "item")
    colors = ", ".join(new_item.get("colors", [])) or "n/a"
    style_tags = ", ".join(new_item.get("style_tags", [])) or "n/a"
    item_block = (
        f"New item: {title}\n"
        f"  category: {category}\n"
        f"  colors: {colors}\n"
        f"  style tags: {style_tags}"
    )

    if not items:
        # Empty wardrobe — ask for general styling ideas, no named pieces.
        user_prompt = (
            f"{item_block}\n\n"
            "The user has not entered any wardrobe items yet. Suggest 1-2 ways to "
            "style this thrifted piece in general terms: what kinds of garments, "
            "shoes, and accessories pair well with it, and the overall vibe it "
            "suits. Keep it to 2-4 sentences. Do not invent specific items the "
            "user owns."
        )
    else:
        wardrobe_lines = "\n".join(
            f"  - {it.get('name', it.get('id', 'item'))} "
            f"({it.get('category', '?')}; "
            f"colors: {', '.join(it.get('colors', [])) or 'n/a'}; "
            f"tags: {', '.join(it.get('style_tags', [])) or 'n/a'})"
            for it in items
        )
        user_prompt = (
            f"{item_block}\n\n"
            f"The user's wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with specific "
            "pieces named from the wardrobe above. Reference the wardrobe pieces "
            "by name. Add a quick styling tip (tuck, roll, layer, etc.). Keep it "
            "to 2-4 sentences and only use pieces that appear in the wardrobe."
        )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are FitFindr, a sharp secondhand-fashion stylist. You give "
                    "concise, concrete outfit advice — no fluff, no preamble."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no outfit means there is nothing to caption.
    if not outfit or not outfit.strip():
        return (
            "Error: cannot create a fit card without an outfit suggestion. "
            "Run suggest_outfit first and pass its result here."
        )

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    user_prompt = (
        f"Thrifted item: {title} — {price_str} on {platform}.\n"
        f"Outfit: {outfit}\n\n"
        "Write a short, casual OOTD caption (2-4 sentences) for posting this look "
        "on Instagram or TikTok. Mention the item, its price, and the platform "
        "naturally — once each. Capture the outfit's vibe in specific terms. "
        "Sound like a real person, not a product description. Reply with the "
        "caption only."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You write punchy, authentic secondhand-fashion captions with "
                    "personality. No hashtag spam, no corporate tone."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        # Higher temperature so repeated calls on the same input vary.
        temperature=1.1,
    )
    return response.choices[0].message.content.strip()
