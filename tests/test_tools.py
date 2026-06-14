"""
Tests for the three FitFindr tools.

search_listings is pure (no network) and is tested directly. suggest_outfit and
create_fit_card call the Groq LLM, so their happy-path tests are skipped when
GROQ_API_KEY is not configured; their non-LLM failure modes are always tested.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM call",
)


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, not an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_matches_compound_sizes():
    # "M" should match listings sized "S/M" or "M/L", not e.g. "US 9".
    results = search_listings("top", size="M", max_price=None)
    for item in results:
        size = item["size"].lower()
        flexible = any(
            m in size for m in ("one size", "oversized", "adjustable", "fits")
        )
        assert flexible or "m" in {
            t for t in size.replace("/", " ").split()
        } or "m" in size.split()


def test_search_sorted_by_relevance():
    results = search_listings("vintage band graphic tee", size=None, max_price=None)
    assert len(results) >= 2
    # Top result should be a tops listing tagged for graphic/band tees.
    assert results[0]["category"] == "tops"


# ── suggest_outfit ────────────────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_does_not_crash():
    # Failure mode: empty wardrobe must not raise. Without a key it raises a
    # config ValueError before any wardrobe logic; with a key it returns advice.
    new_item = search_listings("vintage graphic tee", max_price=50)[0]
    if not os.environ.get("GROQ_API_KEY"):
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            suggest_outfit(new_item, get_empty_wardrobe())
    else:
        result = suggest_outfit(new_item, get_empty_wardrobe())
        assert isinstance(result, str) and result.strip()


@needs_groq
def test_suggest_outfit_with_wardrobe_returns_text():
    new_item = search_listings("vintage graphic tee", max_price=50)[0]
    result = suggest_outfit(new_item, get_example_wardrobe())
    assert isinstance(result, str)
    assert len(result.strip()) > 0


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    # Failure mode: empty/whitespace outfit → error string, never an exception.
    new_item = {"title": "Faded Band Tee", "price": 22, "platform": "depop"}
    result = create_fit_card("", new_item)
    assert isinstance(result, str)
    assert result.lower().startswith("error")

    result_ws = create_fit_card("   \n  ", new_item)
    assert result_ws.lower().startswith("error")


@needs_groq
def test_create_fit_card_varies_on_repeat():
    new_item = search_listings("vintage graphic tee", max_price=50)[0]
    outfit = "Pair with baggy jeans and chunky white sneakers for a 90s grunge look."
    cards = {create_fit_card(outfit, new_item) for _ in range(3)}
    # Higher temperature should produce variation across runs.
    assert len(cards) > 1
