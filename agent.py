"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# Letter sizes that are unambiguous on their own (won't appear as stray words).
_LETTER_SIZES = r"xxs|xs|xl|xxl"


def _parse_query(query: str) -> dict:
    """
    Extract search parameters from a natural-language query.

    Pulls out an optional price ceiling ("under $30", "$30", "below 25") and an
    optional size ("size M", "size 8", or a bare XXS/XS/XL/XXL), then strips
    those phrases out so what remains is the descriptive keywords.

    Returns:
        {"description": str, "size": str | None, "max_price": float | None}
    """
    text = query.strip()
    lowered = text.lower()

    # --- price ---
    max_price = None
    price_match = (
        re.search(r"\$\s*(\d+(?:\.\d{1,2})?)", lowered)
        or re.search(
            r"(?:under|below|less than|max(?:imum)?|up to)\s+\$?\s*(\d+(?:\.\d{1,2})?)",
            lowered,
        )
    )
    if price_match:
        max_price = float(price_match.group(1))

    # --- size ---
    size = None
    size_match = re.search(r"\bsize\s+([a-z0-9]+(?:\.\d)?(?:/[a-z0-9]+)?)\b", lowered)
    if size_match:
        size = size_match.group(1).upper()
    else:
        letter_match = re.search(rf"\b({_LETTER_SIZES})\b", lowered)
        if letter_match:
            size = letter_match.group(1).upper()

    # --- description: remove the price and size phrases we just consumed ---
    description = text
    description = re.sub(
        r"(?:under|below|less than|max(?:imum)?|up to)\s+\$?\s*\d+(?:\.\d{1,2})?",
        " ",
        description,
        flags=re.IGNORECASE,
    )
    description = re.sub(r"\$\s*\d+(?:\.\d{1,2})?", " ", description)
    description = re.sub(
        r"\bsize\s+[a-z0-9]+(?:\.\d)?(?:/[a-z0-9]+)?\b",
        " ",
        description,
        flags=re.IGNORECASE,
    )
    description = re.sub(rf"\b({_LETTER_SIZES})\b", " ", description, flags=re.IGNORECASE)
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search. This is the branch point — if nothing matches, we set an
    # error and return BEFORE calling the LLM tools.
    session["search_results"] = search_listings(
        parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    if not session["search_results"]:
        bits = [f"'{parsed['description'] or query.strip()}'"]
        if parsed["size"]:
            bits.append(f"in size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:g}")
        session["error"] = (
            "No listings matched " + " ".join(bits) + ". "
            "Try raising your budget, changing the size, or using fewer keywords."
        )
        return session

    # Step 4: select the top-ranked listing to style.
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit. The exact selected_item dict is passed through —
    # no re-prompting, no hardcoded values.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: turn that suggestion + item into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done — error stays None on the happy path.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
