# FitFindr 🛍️

FitFindr is a multi-tool AI agent that helps you shop secondhand. You describe what
you're after in plain language ("vintage graphic tee under $30, size M"), and the agent
finds a matching listing, styles it against your wardrobe, and writes a shareable "fit
card" caption for it.

It chains three tools through a planning loop that **decides what to do next based on what
each tool returns** — it does not blindly run all three every time.

## 🎬 Demo

[Watch the demo video](https://drive.google.com/file/d/1LovtXZIb268qR4-pAGfsayY4K4HAKCo7/view?usp=sharing)

---

## Setup

```bash
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the project root (free key at
[console.groq.com](https://console.groq.com)). The two LLM-backed tools read it via
`load_dotenv()`:

```
GROQ_API_KEY=your_key_here
```

## Run

```bash
python app.py            # launches the Gradio UI (check the terminal for the URL,
                         # usually http://localhost:7860)
python agent.py          # CLI: runs a happy-path query and the no-results branch
python -m pytest tests/  # 9 tests (LLM tests skip if GROQ_API_KEY is unset)
```

---

## How it works (architecture)

```
User query + wardrobe
        │
        ▼
   run_agent()  ──────────────────────────────────────────────┐
        │                                                      │
        ├─ _parse_query() → {description, size, max_price}     │
        │                                                      │
        ├─ search_listings(description, size, max_price)       │
        │        │ results == []                               │
        │        ├──► set session["error"] (what failed +      │
        │        │     what to try) → RETURN early ────────────┤
        │        │ results == [item, ...]                      │
        │        ▼                                             │
        │   session["selected_item"] = results[0]              │
        │        │                                             │
        ├─ suggest_outfit(selected_item, wardrobe)  [LLM]      │
        │        │ (empty wardrobe → general advice)           │
        │        ▼                                             │
        │   session["outfit_suggestion"] = "<text>"            │
        │        │                                             │
        └─ create_fit_card(outfit_suggestion, selected_item)   │
                 │ (empty outfit → "Error: ..." string)        │
                 ▼                            early return ◄────┘
           session["fit_card"] = "<caption>"
                 │
                 ▼
           return session  →  app.py maps it to the 3 UI panels
```

---

## Tool inventory

### 1. `search_listings(description, size, max_price) -> list[dict]`
**Purpose:** Find secondhand listings matching the user's request. This is a pure,
deterministic function — no LLM — so search results are repeatable and testable.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `description` | `str` | Keywords describing the item (e.g. `"vintage graphic tee"`). Tokenized and matched against each listing's title, description, style_tags, category, and colors. |
| `size` | `str \| None` | Desired size (e.g. `"M"`, `"8"`). `None` skips size filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips price filtering. |

**Output:** A `list[dict]` of full listing dicts (`id`, `title`, `description`, `category`,
`style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by
relevance (best first). Returns `[]` when nothing matches — never raises.

**How it ranks:** tokens found in `style_tags` score 2 points; tokens found in
title/description/category/colors score 1; each token counts once. Listings scoring 0 are
dropped. Size matching is token-based (so `"M"` matches `"S/M"` and `"M/L"` but not
`"US 9"`); only genuinely size-agnostic listings (`"one size"`, `"adjustable"`,
`"fits most"`) bypass the size filter.

### 2. `suggest_outfit(new_item, wardrobe) -> str`
**Purpose:** Style the chosen listing against the user's wardrobe. Calls the Groq LLM
(`llama-3.3-70b-versatile`).

| Parameter | Type | Meaning |
|-----------|------|---------|
| `new_item` | `dict` | The listing to style (the loop passes `selected_item`). Its title/category/colors/style_tags go into the prompt. |
| `wardrobe` | `dict` | `{"items": [...]}` in the wardrobe schema. May be empty. |

**Output:** A non-empty `str`. With wardrobe items, it names specific pieces and adds a
styling tip (tuck/layer/roll). With an empty wardrobe, it returns general styling advice
instead of naming pieces the user doesn't own.

### 3. `create_fit_card(outfit, new_item) -> str`
**Purpose:** Turn the outfit into a short, casual, social-ready caption. Calls the LLM at
**temperature 1.1** so repeated calls on the same input vary.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `outfit` | `str` | The styling string from `suggest_outfit`. |
| `new_item` | `dict` | The listing — supplies title, price, and platform for the caption. |

**Output:** A `str` caption mentioning the item, price, and platform once each. If `outfit`
is empty/whitespace, it returns an `"Error: ..."` string (no LLM call, no exception).

---

## The planning loop — what the agent *decides*

`run_agent(query, wardrobe)` in [agent.py](agent.py) is a deterministic pipeline with one
real decision point. The order (search → suggest → card) is fixed because each step
consumes the previous step's output, but **whether the later steps run at all is
conditional.**

1. **Parse.** `_parse_query()` pulls a price ceiling (`"under $30"`, `"$30"`), a size
   (`"size M"`, `"size 8"`, or a bare `XXS/XS/XL/XXL`), and strips those phrases so the
   remainder becomes the search description. This is regex-based, not an LLM call, so
   parsing is fast and predictable.

2. **Search, then branch.** The agent calls `search_listings`. This is the decision point:
   - **If results are empty:** it writes a specific message into `session["error"]`
     (naming the description, size, and price that failed, plus what to try) and
     **returns immediately.** `suggest_outfit` and `create_fit_card` are *never called
     with empty input.* This is the difference between a real planning loop and an
     unconditional pipeline.
   - **If results exist:** it sets `selected_item = results[0]` (the top-ranked listing)
     and proceeds.

3. **Suggest, then card.** Only on the success path does the agent style the item and
   generate a caption, threading the *exact* `selected_item` dict and `outfit_suggestion`
   string from one tool into the next.

The loop is "done" when it returns the session: on failure `session["error"]` is set and
the output fields are `None`; on success `error` is `None` and all output fields are
populated.

---

## State management

A single `session` dict (built by `_new_session()`) is the one source of truth for an
interaction. The planning loop is the **only writer** — tools are pure functions of their
arguments and never touch the session directly. The loop stores each tool's return value,
then passes the stored value into the next tool.

| Key | Set by | Consumed by |
|-----|--------|-------------|
| `query` | caller | parser |
| `parsed` (`description`, `size`, `max_price`) | parser | search_listings |
| `wardrobe` | caller | suggest_outfit |
| `search_results` | search_listings | item selection |
| `selected_item` | loop (`search_results[0]`) | suggest_outfit, create_fit_card |
| `outfit_suggestion` | suggest_outfit | create_fit_card |
| `fit_card` | create_fit_card | UI |
| `error` | loop (on failure) | UI (checked first) |

State passing is **by reference**, verified with spies: the exact dict stored in
`session["selected_item"]` is the same object handed to both `suggest_outfit` and
`create_fit_card`, and the exact `outfit_suggestion` string is the one handed to
`create_fit_card` (identity checks return `True`). There is no re-prompting or hardcoding
between steps.

---

## Error handling (per tool)

| Tool | Failure mode | What the agent does |
|------|--------------|---------------------|
| `search_listings` | No listing matches the query | Returns `[]`; the loop sets a specific `session["error"]` and stops before the LLM tools run. |
| `suggest_outfit` | Wardrobe is empty (`items == []`) | Switches to a general-advice prompt and returns useful styling text — no crash, no empty string. |
| `create_fit_card` | `outfit` is empty/whitespace | Returns a descriptive `"Error: ..."` string without calling the LLM or raising. |

**Concrete example from testing** (full run saved in
[docs/error_handling_verification.txt](docs/error_handling_verification.txt)):

```
>>> run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
error          : No listings matched 'designer ballgown' in size XXS under $5.
                 Try raising your budget, changing the size, or using fewer keywords.
selected_item  : None
outfit / card  : None / None
```

Spies confirmed `suggest_outfit` and `create_fit_card` were each called **0 times** on this
path — the agent recovers by telling the user *what failed and what to try*, not just "no
results."

---

## Spec reflection

What changed between the planning.md spec and the final implementation:

- **Return types.** My first draft of the Tool 2/3 specs had `suggest_outfit` and
  `create_fit_card` returning structured dicts (`{text, paired_item_ids}`,
  `{caption}`). The starter stubs and `agent.py` expected plain **strings**, so I
  implemented strings and rewrote those planning.md sections to match. Lesson: the
  interface the rest of the system expects wins over a nicer-looking spec.
- **Search size matching.** The spec originally treated `"oversized"` as a size wildcard.
  Testing surfaced that `"black combat boots size 8"` returned an oversized *flannel*
  (it slipped through the shoe-size filter and won on a shared "black" color). Those
  listings already carry a real size token (`"XL (oversized)"`), so I removed `"oversized"`
  from the wildcard set in both the code and the spec. The query now correctly returns
  shoes.
- **What held up well.** The single-decision planning loop and the session-as-single-
  source-of-truth design were correct from the start and needed no rework — having them
  written down made the implementation and the state-passing verification straightforward.

---

## AI usage

I used Claude (Claude Code) as a pair-programmer throughout, driven by the specs in
`planning.md`. Two concrete instances:

**1. Implementing `search_listings`.**
- *Input I gave it:* the Tool 1 block from planning.md (the three parameters, the
  filter rules, the relevance-scoring formula, and the empty-result behavior), plus the
  field list from `utils/data_loader.py`.
- *What it produced:* a function using `load_listings()` that applied the price/size
  filters, scored by keyword overlap (style_tags weighted ×2), dropped zero-score
  listings, and returned sorted dicts.
- *What I changed/overrode:* the generated size filter treated `"oversized"` as a
  match-anything wildcard. After a test (`"combat boots size 8"`) returned a flannel
  shirt, I overrode it to exclude `"oversized"`/`"fits oversized"` from the wildcard
  markers so apparel with a real size token no longer leaks into shoe-size searches.

**2. Implementing the planning loop in `agent.py`.**
- *Input I gave it:* the Planning Loop pseudocode, the State Management table, and the
  architecture diagram from planning.md.
- *What it produced:* `run_agent()` building the session, parsing the query, branching on
  empty search results with an early return, and threading state between tools.
- *What I changed/verified before trusting it:* I confirmed it branches on the
  `search_listings` result (rather than calling all three tools unconditionally), then
  wrote a spy-based check to verify the *exact* `selected_item` dict and
  `outfit_suggestion` string flow between tools by identity, and that the no-results path
  calls the LLM tools 0 times. I also wrote `_parse_query` to be regex-based rather than an
  extra LLM call, to keep parsing deterministic and cheap.

---

## Project layout

```
├── agent.py        # run_agent() planning loop + _parse_query()
├── app.py          # Gradio UI + handle_query()
├── tools.py        # search_listings, suggest_outfit, create_fit_card
├── planning.md     # design spec (tools, loop, state, errors, diagram)
├── data/           # listings.json (40 listings) + wardrobe_schema.json
├── utils/          # data_loader.py
├── tests/          # test_tools.py (9 tests) + conftest.py
└── docs/           # error_handling_verification.txt
```
