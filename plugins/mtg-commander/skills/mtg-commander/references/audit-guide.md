# Deck Audit Guide

Reference for the Deck Auditor agent. This mode answers a different question than the builder: *given a deck that already exists, what would make it win more?* The builder optimizes in a vacuum; the auditor optimizes against the tournament field.

---

## Table of Contents

1. [When to audit](#1-when-to-audit)
2. [Evidence hierarchy](#2-evidence-hierarchy)
3. [The workflow](#3-the-workflow)
4. [Reading cedhstats](#4-reading-cedhstats)
5. [Reading EDHTop16](#5-reading-edhtop16)
6. [Building the swap sheet](#6-building-the-swap-sheet)
7. [New-card screening](#7-new-card-screening)
8. [Cards you must not recommend cutting](#8-cards-you-must-not-recommend-cutting)
9. [Report structure](#9-report-structure)
10. [Failure modes](#10-failure-modes)

---

## 1. When to audit

Audit mode triggers when the user supplies an **existing deck** rather than asking for a build:

- "Evaluate my deck"
- "Is this list optimal?"
- "What should I swap?"
- "How does my list compare to the meta?"
- A Moxfield, Archdekt, or EDHTop16 URL plus any request for feedback

Build mode is for "make me a deck." Audit mode is for "make this deck better." If the user supplies a deck **and** asks for a rebuild, audit first, then offer targeted swaps — a full rebuild discards the pilot's tuning and preferences.

### Scope gate

Audit mode requires a **competitive-format deck** (cEDH, high power, or an explicitly tournament-oriented list) for the tournament-data portions. For casual or bracket 1–3 decks:

- Skip EDHTop16 and cedhstats entirely; their populations do not represent casual play.
- Run only the structural checks (composition, curve, singleton, color identity) and skip sections 4, 5, and 7.
- Say plainly that the tournament data does not apply rather than presenting it as weak evidence.

---

## 2. Evidence hierarchy

Rank every claim by how much evidence supports it. The failure mode of an unaided audit is a confident list of swaps built on vibes; the hierarchy is what keeps recommendations honest.

| Tier | Signal | Weight | Notes |
|---|---|---|---|
| 1 | **Top-list presence** — how many of the fetched top-finishing lists play the card | Strongest for established cards | Direct evidence that winning pilots chose it |
| 2 | **cedhstats inclusion %** — share of the last 6 months of parsed decklists | Strong | Reflects the whole field, not just winners |
| 3 | **PPG delta with a clear signal** | Moderate | Correlational. Use to confirm or challenge tiers 1–2, never alone |
| 4 | **Lift** | Weak | Novelty detector. High lift plus low inclusion means "distinctive to this archetype," not "good" |
| 5 | **Your judgment** | Lowest | Use for mechanics and sequencing, and label it as such |

**Rules that follow from the hierarchy:**

- A card in 7 of 8 top lists with a negative PPG delta **stays**. The delta is correlational and top-list presence is direct.
- A card below 10% inclusion with a strong PPG delta is a **test candidate**, not a recommendation. Say "test this," not "play this."
- Never rank a swap sheet by PPG delta alone. Rank by top-list presence first.
- If the two sites disagree, say so and follow top-list presence. Do not average them into a fake consensus.

### Sample-size honesty

cedhstats prints the number of parsed decklists and a confidence interval per card. EDHTop16 prints entry counts. Always report these. A 6.7% inclusion figure comes from a small subsample; a 96% figure does not. New cards have small samples **by definition** — say so.

---

## 3. The workflow

Run these steps in order. Steps 1–3 are scripted; steps 4–6 are yours.

### Step 1 — Ingest the deck, keeping boards separate

```bash
python ${SKILL_DIR}/scripts/deck_sources.py moxfield --id <publicId>
python ${SKILL_DIR}/scripts/deck_sources.py archidekt --id <numericId>
python ${SKILL_DIR}/scripts/deck_sources.py file --path deck.txt
```

The script emits each board separately: `commanders`, `mainboard`, `maybeboard`, `sideboard`, `companions`. **Never merge boards.** A maybeboard card is a card the pilot is *considering*; describing it as part of the deck is a factual error the user will catch. If you catch yourself writing "your deck plays X" about a maybeboard card, stop and re-check which array it came from.

`deck_total` counts commanders + mainboard only. If it is not 100, resolve that before analyzing — a truncated export will silently skew every percentage that follows.

### Step 2 — Fetch tournament data for the commander(s)

```bash
python ${SKILL_DIR}/scripts/meta_sources.py cedhstats --commanders "A" "B"
python ${SKILL_DIR}/scripts/meta_sources.py edhtop16 --commanders "A" "B" --period ONE_YEAR --top-decks 8
```

**Partner commanders:** pass both names. `--period` accepts `ONE_MONTH`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`. Prefer `ONE_YEAR` for stability and `THREE_MONTHS` when the user asks what is *currently* good. Run both if the recommendation hinges on a recent shift.

**Commander pairing order:** EDHTop16 only serves one ordering of a partner pair and returns HTTP 500 for the reverse. The script tries both; if it still fails, the commander has no recorded entries and you must say so rather than inventing data.

### Step 3 — Compute the comparison

```bash
python ${SKILL_DIR}/scripts/audit_compare.py \
  --deck deck.json --cedh cedh.json --edhtop edh.json --since 2025-01-01
```

This produces the deterministic tables: composition, per-card signals, `missing_core`, `cuts`, and `recent_cards`. Do not recompute these numbers by hand in prose — quote the script. Hand-counted percentages drift and the user will notice.

`--since` should be roughly 12–18 months back. It screens by **first printing**, so reprints in recent precons do not masquerade as new designs.

### Step 4 — Classify the deck

Before recommending anything, state in one or two sentences what the deck is trying to do and whether the list already matches the archetype's consensus shell. A deck that is 65 of 100 cards inside the top-list core is a *tune*. A deck that is 40 of 100 is a *rebuild*. The recommendation style differs sharply, and saying which one applies sets the user's expectations correctly.

### Step 5 — Build the swap sheet

Follow section 6. Every swap needs a cut, an add, and a mechanical reason — not just a statistical one.

### Step 6 — Screen new cards

Follow section 7.

---

## 4. Reading cedhstats

The `/commanders/<slug>/cards` page is the most useful single page in cEDH deck analysis. Fields:

| Field | Meaning | How to use |
|---|---|---|
| **Inclusion %** | Share of parsed decklists playing the card | Tier 2 evidence; the field's consensus |
| **Printed count** | e.g. `2045 / 2047` | Sample size; sanity-check the percentage |
| **Group** | Locked core / Core shell / Shell edge / Signature / Spice / Flex / Deep cut | Structural role. "Locked core" is a deck-defining card |
| **Lift** | How much more common the card is here than in the field | Novelty/identity detector. High lift + low inclusion = signature, not staple |
| **PPG delta** | Tournament points per game, with vs. without | Tier 3. Positive = pilots playing it scored higher |
| **CI low/high** | 90% confidence interval | If the interval spans zero, treat the signal as noise |
| **Clear signal** | Site's own filter for a CI that excludes zero | Use this rather than eyeballing; it is the site's threshold |

**Core shell vs signature.** The core shell is what the deck almost always plays and is the strongest evidence for a cut decision. Signature cards are what make the deck distinct — cutting them can flatten the deck into a generic list even when their PPG signal looks weak.

**The warning-signs block** on the cards page lists cards with *negative* clear signals. Treat these as prompts to investigate overlap with the deck's own cards, not as automatic cuts — many of them are protection or interaction that shows a negative average because pilots reach for them in losing positions.

**PPG is not causal.** A card played more often by experienced pilots will look better. A card played as a desperate answer will look worse. Say "the data correlates with" rather than "the card causes."

---

## 5. Reading EDHTop16

| Surface | What it gives | Caveat |
|---|---|---|
| Commander summary | Entries, meta %, conversion | Conversion is the better quality signal — meta % only measures popularity |
| **Staples tab** | Play rate per card type among entries | This is the field-wide number; it differs from cedhstats' 6-month parse |
| **Top entries** | Pilot, event, size, placement, record | Placement matters: a 1st place at 268 players outweighs a 5th at 57 |
| **Top decklists** | Actual 98-card lists | The strongest evidence available: what winning pilots actually registered |

**Fetching decklists.** `--top-decks N` downloads the N highest-placed entries and parses every card. Use 5–8. Fewer than 5 and a single pilot's preferences dominate; more than 8 and you are mostly measuring bulk popularity already covered by the staples tab.

**Duplicate lists.** Pilots often re-register the same list across events. If several top entries are the same list, the "6 of 8 lists play it" figure overstates independent support. Check whether deck URLs or card lists repeat and say so when they do.

**Time and size filters.** Restrict to meaningful events when the user cares about serious competition. `--min-size 50` filters out small local events; `--period THREE_MONTHS` answers "what is working now." State which filters you used — a recommendation from a 12-month unfiltered sample is different advice from a 3-month filtered one.

---

## 6. Building the swap sheet

### Ranking cuts

A cut candidate needs at least one of:

1. **Low top-list presence** — below roughly a third of fetched lists (e.g. ≤2 of 8)
2. **Low field inclusion** — below ~35% in cedhstats
3. **Negative PPG with a clear signal** — CI entirely below zero

Then apply the overrides in section 8 before recommending any cut.

Rank cuts by *how much evidence argues against them*, not by PPG alone. A card at 0/8 top lists and 11% inclusion is a much safer cut than a card at 4/8 and 65% with a mildly negative delta.

### Ranking adds

Rank by top-list presence, then inclusion, then PPG. Prefer:

- Cards in the deck's **color identity** and legal
- Cards that fill a **role the cut leaves empty** (do not swap interaction for a win-more)
- Cards the pilot can actually buy — check `price_usd` and mention the cost when it is material

### The mechanical reason is mandatory

Every swap gets a one-line explanation of what the card *does* in this deck, not just that it is popular. "72.8% inclusion" is a statistic; "taps Rograkh for any color, fixes blue and red, and is an Urza's Saga target at mana value 1" is a reason. The user can get statistics anywhere — the value of this skill is connecting the number to the deck's engine.

### Calibrate the size of the recommendation

| Deck vs. top-list core | Recommendation |
|---|---|
| ≥ 60 of 100 cards in the core | 3–6 swaps, framed as a tune. Explicitly say the deck is already well-built |
| 40–59 | 6–10 swaps plus a note on which axis is furthest off (mana, interaction, win conditions) |
| < 40 | Recommend a rebuild, or a phased plan. A 20-card swap list is not actionable |

### Offer a test tier

Separate high-confidence swaps from experiments. New cards and low-sample signals belong in a clearly labeled test tier with a game count ("play 15–20 games and track these three failure modes"). This keeps the user from making eight speculative changes at once and losing the ability to attribute the result.

---

## 7. New-card screening

The user asking for "new cards from recent expansions" wants a screen, not a list of everything printed.

1. Use `recent_cards` from `audit_compare.py` — it is already filtered to first printings at or after `--since`.
2. For each candidate, work out **what role it would fill** and whether the deck has a gap there.
3. Check whether top pilots have adopted it. A brand-new card will have small samples by definition; top-list presence among recent lists is more informative than its PPG delta.
4. Discard cards that are new but do not touch the deck's engine, even if they are strong in the abstract. A card that is good in a different archetype is not a recommendation.

**Be explicit about the two kinds of "new":** genuinely new designs from the last few sets, versus cards that are new *to this archetype* because a recent set made them viable. The second category is often where the real gains are.

**Novelty is not value.** Say when a new card is genuinely untested. Do not present a 6.7% inclusion figure with a wide confidence interval as if it were a settled result.

---

## 8. Cards you must not recommend cutting

Override the statistical screen for:

- **Engine and identity cards** — cards the deck's entire plan routes through, even if the average PPG looks weak. In a land-untap deck, that means the untappers and the land tutors.
- **Free interaction** — pitch spells and zero-cost answers. Their average performance is distorted because pilots hold them for the turn that matters.
- **Protection** — counterspells and protection pieces get played in losing positions, so they show negative deltas while being necessary.
- **Cards with high top-list presence and negative PPG** — direct evidence beats a correlational average. Say why you are keeping it.
- **Singleton role players** — the only answer the deck has to a category of threat.

When a card is in this category but genuinely looks weak, recommend **testing** an alternative rather than cutting outright.

---

## 9. Report structure

Use this structure for audit output. Keep it tight — the user wants decisions, not a data dump.

```markdown
## Bottom line
Two or three sentences: how close the deck is to the consensus core, what kind of
change is warranted (tune / rebuild), and what the single biggest gap is.

## Recommended swaps
| Cut | Add | Why (mechanical) |
One row per swap. Then a copy-paste block:

-1 Card
+1 Card

## Optional / test tier
Swaps that are defensible but lower confidence, with the reason they are lower.

## New cards
Already playing and validated / missing and worth adding / new but not for this deck.
Group by verdict, not by set.

## Do not cut
Cards with weak average signals that earn their slot, with the reason.

## Suggested testing plan
Numbered, short. Include what to track so the pilot can attribute results.

## Caveats
Sample sizes, correlational nature of PPG, duplicate lists, meta dependence.
```

### Formatting rules

- Lead with the decision, then the evidence. Never open with a table of statistics.
- Include the concrete numbers (top-list counts, inclusion %, PPG with CI) inline in the "Why" column — they make the recommendation checkable.
- Mark the source for each claim type: "top lists" (EDHTop16), "field inclusion" (cedhstats), "PPG" (cedhstats), "my read" (judgment).
- When offering a deck guide as a file, write it to the working directory and name the data vintage in the header (all three sources plus the date pulled).

---

## 10. Failure modes

| Failure | Symptom | Fix |
|---|---|---|
| **Board bleed** | Describing a maybeboard card as part of the deck | Read `boards.maybeboard` separately; verify placement before naming any card |
| **PPG overreach** | Cutting a 7/8 top-list card because its delta is −0.05 | Apply section 8; weigh top-list presence first |
| **Recency bias** | Recommending every card from the newest set | Require a role gap plus adoption evidence |
| **Sample-size blindness** | Quoting 6.7% as if it were 96% | Report CI and decklist counts with the number |
| **Hand-computed stats** | Percentages in prose that disagree with the scripts | Quote the script output |
| **Duplicate-list inflation** | "6 of 8 lists" when 4 are the same list | Check and disclose |
| **Format mismatch** | Applying cEDH data to a bracket 3 deck | Apply the scope gate in section 1 |
| **Unbuyable recommendations** | A swap sheet full of $200 cards without saying so | Report `price_usd` and offer a budget alternative |
| **Silent staleness** | Presenting data without saying when it was pulled | Name the date and the filters |
