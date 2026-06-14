# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock secondhand-clothing dataset (loaded via `load_listings()`) and returns the
listings that match the user's request. It hard-filters by size and price, then ranks the
survivors by how well their text and style tags overlap the user's free-text description.

**Input parameters:**
- `description` (str): The free-text item the user wants, e.g. `"vintage graphic tee"`. Tokenized
  and matched against each listing's `title`, `description`, `style_tags`, `category`, and `colors`.
- `size` (str, optional, default `None`): Desired size, e.g. `"M"`. A listing passes the size
  filter if its `size` field contains the requested token (case-insensitive substring match) OR the
  listing's `size` indicates it is size-flexible (`"one size"`, `"oversized"`, `"adjustable"`,
  `"fits most"`). When `None`, the size filter is skipped.
- `max_price` (float, optional, default `None`): Inclusive price ceiling. A listing passes if
  `listing["price"] <= max_price`. When `None`, the price filter is skipped.

**What it returns:**
A `list[dict]`, sorted by descending relevance score. Each element is a full listing dict carried
straight from the dataset — `id`, `title`, `description`, `category`, `style_tags`, `size`,
`condition`, `price`, `colors`, `brand`, `platform`. Relevance score = (number of query tokens
found in `style_tags`) × 2 + (number of query tokens found in
`title`/`description`/`colors`/`category`) × 1, counting each token once with tags taking
precedence. Listings that score 0 (no keyword overlap) are dropped. Returns `[]` when nothing
passes the size/price filters or nothing scores above 0. The agent selects `results[0]` (top rank)
as the item to style.

**What happens if it fails or returns nothing:**
Returns an empty list `[]`. The planning loop detects the empty list, writes a user-facing message
into session state explaining no items matched and suggesting concrete relaxations (raise
`max_price`, broaden or change the `size`, or use fewer/different keywords), and returns early
**without** calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the chosen listing plus the user's wardrobe and asks the LLM (Groq
`llama-3.3-70b-versatile`) for a short, specific styling recommendation — which existing wardrobe
pieces to pair with the new item and how to wear them (tuck, layer, roll, etc.).

**Input parameters:**
- `new_item` (dict): A single listing dict (the `selected_item` chosen by the planning loop from
  `search_listings` results). Its `title`, `category`, `colors`, `style_tags` are formatted into the
  prompt.
- `wardrobe` (dict): A wardrobe in the schema format `{"items": [...]}`, where each item has
  `id`, `name`, `category`, `colors`, `style_tags`, and optional `notes`. Supplied by the session
  (from `get_example_wardrobe()` or a user-entered wardrobe).

**What it returns:**
A non-empty `str` containing the styling suggestion, e.g. `"Tuck the front of this tee into your
baggy dark-wash jeans and finish with the chunky white sneakers..."`. When the wardrobe has items,
the prompt instructs the model to name specific wardrobe pieces and add a styling tip; the returned
string is the model's text response, stripped.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool does not crash — it sends a different prompt asking for
general styling ideas (what kinds of garments/shoes/accessories pair well and the overall vibe)
without inventing pieces the user owns, and returns that advice string. Either way the agent always
gets a usable string to pass to `create_fit_card`. (Configuration failure — a missing
`GROQ_API_KEY` — raises a `ValueError` from `_get_groq_client()`, surfaced to the user as a setup
error rather than silently returning empty.)

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion and the new item into a short, casual, social-ready caption (the kind
you'd post under an outfit photo) via the LLM (Groq `llama-3.3-70b-versatile`) at a high
temperature so repeated calls vary.

**Input parameters:**
- `outfit` (str): The styling string returned by `suggest_outfit`. Used as the styling context in
  the prompt.
- `new_item` (dict): The selected listing dict. Used to pull `title`, `price`, and `platform` into
  the caption.

**What it returns:**
A `str` — the shareable caption text, e.g. `"thrifted this faded band tee off depop for $22 and it
was made for my wide-legs 🖤 full look in stories"`. Mentions the item, price, and platform once
each and nods to the styling. Temperature is set to 1.1 so the same input produces different
captions on repeat calls.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive **error string** (starting
with `"Error:"`) instructing the caller to run `suggest_outfit` first — it does not call the LLM
and does not raise. Missing `price` on `new_item` degrades gracefully to `"a steal"` in the prompt
rather than failing.

---

### Additional Tools (if any)

None for the core build. (Stretch idea: a `refine_search` tool that re-runs `search_listings` with
relaxed parameters when the first search returns nothing.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is a fixed pipeline with early-exit branches, driven by a `session` dict. Pseudocode:

```
1. Parse the user query into description, size, max_price. Store on session.query.
2. results = search_listings(description, size, max_price)
   - IF results == []:
        session.error = "No listings matched. Try raising your max price, changing the
        size, or using fewer keywords."
        session.status = "no_results"
        RETURN session            # <-- early exit, suggest_outfit is NOT called
   - ELSE:
        session.selected_item = results[0]   # top-ranked listing
        session.results = results
3. outfit = suggest_outfit(session.selected_item, session.wardrobe)   # returns a str
   - session.outfit_suggestion = outfit
        # suggest_outfit always returns usable text (specific pairings if the
        # wardrobe has items, general advice if it is empty) — no branch needed.
4. card = create_fit_card(session.outfit_suggestion, session.selected_item)  # returns a str
   - session.fit_card = card
5. RETURN session            # session.error stays None on success
```

The loop's only branch is whether `search_listings` returned an empty list (hard stop, set
`session.error`, return before calling the LLM tools). It is "done" when it returns the session —
on the no-results path `session.error` is a non-empty string and the LLM fields stay `None`; on the
happy path `session.error` is `None` and `outfit_suggestion`/`fit_card` are populated. There is no
open-ended tool-choice reasoning — the order is deterministic (search → suggest → card) because
each step consumes the previous step's output.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (built by `_new_session()` in `agent.py`) is created at the start of the
run and threaded through every step. It holds:

| Key | Set by | Consumed by |
|-----|--------|-------------|
| `query` (str) | caller | query parser |
| `parsed` (dict: description, size, max_price) | query parser | search_listings |
| `wardrobe` (dict) | loaded at session start via `get_example_wardrobe()` / user input | suggest_outfit |
| `search_results` (list[dict]) | search_listings | item selection / debugging |
| `selected_item` (dict) | planning loop (`search_results[0]`) | suggest_outfit, create_fit_card |
| `outfit_suggestion` (str) | suggest_outfit | create_fit_card |
| `fit_card` (str) | create_fit_card | final output to user |
| `error` (str or None) | planning loop | output formatter (checked first) |

Tools are pure functions of their arguments: they receive what they need and return a value; they
do not read or mutate the session directly. The planning loop is the only writer of session state —
it takes each tool's return value and stores it under the right key, then passes the stored value
into the next tool. On the no-results path it sets `error` and returns early, leaving
`outfit_suggestion` and `fit_card` as `None`. This keeps tools testable in isolation and makes the
data flow auditable.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query (empty list after size/price filtering) | Stop the pipeline. Tell the user: "I couldn't find anything matching '<description>' in size <size> under $<max_price>. Try raising your budget, switching to a nearby size, or searching with fewer keywords." Do **not** call suggest_outfit. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Don't crash. Switch to a general-styling prompt (kinds of pieces, shoes, accessories, and vibe that suit the item) and return that advice string, so the user still gets a usable suggestion and a fit card. |
| create_fit_card | Outfit string is empty or whitespace-only | Don't call the LLM and don't raise. Return an error string starting with "Error:" telling the caller to run suggest_outfit first. (Missing `price` degrades to "a steal" in the caption rather than failing.) |

---

## Architecture

```
                          User query: "vintage graphic tee under $30, size M,
                          I wear baggy jeans + chunky sneakers"
                                       │
                                       ▼
   wardrobe (get_example_wardrobe) ─► Planning Loop ──────────────────────────────────┐
                                       │                                               │
                                       ├─► search_listings(description="vintage         │
                                       │       graphic tee", size="M", max_price=30.0)  │
                                       │        │                                       │
                                       │        │ results == []                         │
                                       │        ├──► [ERROR] session.error =            │
                                       │        │     "No listings matched. Raise       │
                                       │        │      price / change size / fewer      │
                                       │        │      keywords."  ──► return session ──┤
                                       │        │                                       │
                                       │        │ results == [item, item, ...]          │
                                       │        ▼                                       │
                                       │   Session: selected_item = search_results[0]   │
                                       │        │  (full listing dict, top relevance)   │
                                       │        ▼                                       │
                                       ├─► suggest_outfit(selected_item, wardrobe) [LLM] │
                                       │        │  (empty wardrobe → general advice;     │
                                       │        │   never raises, always returns text)   │
                                       │        ▼                                       │
                                       │   Session: outfit_suggestion = "<styling str>"  │
                                       │        │                                       │
                                       └─► create_fit_card(outfit_suggestion,            │
                                                          selected_item) [LLM]           │
                                                │  (empty outfit → "Error: ..." string)  │
                                                ▼                                       │
                                            Session: fit_card = "<caption str>"          │
                                                │                                       │
                                                ▼                  early-exit returns ◄──┘
                                            session.error = None
                                                │
                                                ▼
                          Return session ─► formatted output to user
                          (listing details + outfit text + fit card caption,
                           OR session.error message)
```

**Data flow summary:** the user query and wardrobe feed the planning loop; the loop calls the three
tools in order, storing each return value in `session`; `search_listings` empty-result branches off
to an early return (the error path, `session.error` set); the two LLM tools always return usable
strings (general advice / error string in their degraded cases); the final `session` is formatted
into the user's reply.

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **search_listings** — Tool used: **Claude**. Input: the Tool 1 block above (the three
  parameters, the filter + scoring rules, the return shape, and the empty-result behavior) plus the
  field list from `utils/data_loader.py`. Expected output: a function that calls `load_listings()`,
  applies the size + price hard filters, computes the described relevance score (style_tags weighted
  ×2), drops score-0 listings, sorts descending, and returns the matching dicts — returning `[]`
  when nothing passes. Verification: before trusting it, I'll read the code to confirm all three params
  are applied and `[]` is returned on no match, then run 3 queries: (a) `"vintage graphic tee",
  size="M", max_price=30` should surface tees like lst_006/lst_033/lst_002; (b) a `max_price=5`
  query should return `[]`; (c) a `size="XXL"` no-match should return `[]`.
- **suggest_outfit** — Tool used: **Claude**. Input: the Tool 2 block plus the wardrobe schema from
  `data/wardrobe_schema.json`. Expected output: a function taking `new_item` and `wardrobe` that
  builds a Groq `llama-3.3-70b-versatile` prompt and returns a non-empty styling **string**, with a
  separate general-advice prompt for the empty-wardrobe case. Verification: run with
  `get_example_wardrobe()` and a top listing — confirm the text names real wardrobe pieces; run with
  `get_empty_wardrobe()` — confirm it returns general advice text without crashing.
- **create_fit_card** — Tool used: **Claude**. Input: the Tool 3 block. Expected output: a function
  returning a caption **string** that names the item, price, and platform (temperature 1.1 for
  variety) and returns an `"Error: ..."` string when `outfit` is empty. Verification: run with a
  full outfit+item and check the caption contains the price and platform; call it 3× on the same
  input and confirm the captions differ; pass `outfit=""` and confirm an error string (not an
  exception) is returned.

**Milestone 4 — Planning loop and state management:**

- Tool used: **Claude**. Input: the **Planning Loop** pseudocode, the **State Management** table,
  and the **Architecture** diagram above. Expected output: a `run(query, wardrobe)` function that
  builds the `session` dict, calls the three tools in order, implements the empty-results early
  return and the empty-pairings warn-and-continue branch, sets `status`, and returns `session`;
  plus an output formatter that turns `session` into the user-facing text. Verification: I'll trace
  the example query end to end (expecting all three keys populated and `status == "complete"`), then
  run the error path (`max_price=5`, expecting `status == "no_results"` and `suggest_outfit` never
  called — confirmed by leaving `outfit_suggestion`/`fit_card` unset), and the empty-wardrobe path
  (expecting a warning plus a card).

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr needs to do:** FitFindr is a secondhand-fashion shopping agent that takes a user's natural-language request plus their wardrobe and returns a thrift find styled into a complete look. A user request triggers `search_listings` to find matching secondhand items; once a listing is picked, that result triggers `suggest_outfit` to style it against the user's wardrobe, and that suggestion in turn triggers `create_fit_card` to write a shareable caption. If `search_listings` returns no matches, FitFindr stops, explains what to adjust (loosen the budget, change size, broaden the search), and never calls the downstream tools with empty input; likewise it skips `suggest_outfit` when the wardrobe is empty.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — search_listings:**
The loop parses the query into `description="vintage graphic tee"`, `size=None` (none stated),
`max_price=30.0` and calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`.
After filtering to items priced ≤ $30 and scoring keyword/tag overlap, it returns the top 3 — e.g.
`lst_006` "Graphic Tee — 2003 Tour Bootleg Style" ($24, depop, tags include graphic tee + vintage +
grunge), `lst_033` "Vintage Band Tee — Faded Grey" ($19, depop), and `lst_002` "Y2K Baby Tee" ($18,
depop). The loop stores all three in `session.results` and sets
`session.selected_item = results[0]` (lst_006).

**Step 2 — suggest_outfit:**
With a non-empty result, the loop calls `suggest_outfit(new_item=lst_006,
wardrobe=<example wardrobe>)`. The tool formats the graphic tee and the wardrobe into an LLM prompt
and the model pairs it with complementary pieces sharing its streetwear/grunge tags. It returns a
**string** such as: `"Tuck the front of this bootleg tee into your baggy dark-wash jeans and finish
with the chunky white sneakers — throw the black denim jacket over it for that 90s grunge layered
look."`, stored in `session.outfit_suggestion`.

**Step 3 — create_fit_card:**
The loop calls `create_fit_card(outfit=session.outfit_suggestion, new_item=lst_006)`. Since the
outfit string is non-empty, it calls the LLM (temperature 1.1) and returns a **string** such as:
`"scored this 2003 bootleg graphic tee off depop for $24 🖤 tucked into my baggy jeans + chunky
sneaks, denim jacket on top — full 90s look in stories"`, stored in `session.fit_card`. The loop
leaves `session.error = None` and returns the session.

**Final output to user:**
FitFindr shows the chosen find, the styling tip, and the caption — roughly:

> **Found it:** *Graphic Tee — 2003 Tour Bootleg Style* — $24, Good condition, on Depop.
> **How to style it:** Tuck the front into your baggy dark-wash jeans, add your chunky white
> sneakers, and layer the black denim jacket over it for a 90s grunge look.
> **Fit card:** "scored this 2003 bootleg graphic tee off depop for $24 🖤 tucked into my baggy
> jeans + chunky sneaks, denim jacket on top — full 90s look in stories"
