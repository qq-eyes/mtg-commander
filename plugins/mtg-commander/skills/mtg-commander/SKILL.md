---
name: mtg-commander
description: >
  MTG Commander deck builder and deck auditor. Build synergy-dense,
  format-legal, budget-compliant 100-card Commander decklists from scratch, or
  audit an existing list against real tournament data from EDHTop16 and
  cedhstats to recommend swaps. Handles partner commanders, cEDH lists, and
  new-card screening from recent sets. Triggers on phrases like "build a
  commander deck", "MTG deck", "commander deck", "EDH deck", "build me a deck",
  "100-card deck", "commander pipeline", "deck builder", and on audit requests
  such as "evaluate my deck", "is this list optimal", "what should I swap",
  "how does my deck compare to the meta", "deck help", or any message that
  includes a Moxfield, Archidekt, or EDHTop16 deck link alongside a request for
  feedback. Use this skill whenever a Commander deck is being built, critiqued,
  or tuned, even if the user does not say "deck builder".
license: Apache-2.0. Copyright 2026 Michael Connelly; modifications Copyright 2026 Paul Baker. See LICENSE.txt and NOTICE.
compatibility: Requires Python 3.10+ (standard library only) and network access to Scryfall, Moxfield, Archidekt, cedhstats, and EDHTop16.
metadata:
  author: Michael Connelly (original); Paul Baker (modifications)
  version: "2.0.0"
  model_awareness: opus-4-7
  last_audited: "2026-10-18"
---

# MTG Commander Deck Builder & Auditor

Two modes sharing one toolkit:

- **Build mode** — a multi-agent pipeline that constructs optimized, format-legal,
  budget-compliant Commanders decklists from intake parameters.
- **Audit mode** — evaluate an existing deck against tournament data and produce a
  swap sheet. This is the mode to use whenever the user supplies a deck.

Both modes share `scripts/card_lookup.py` (Scryfall) and the reference library.
Audit mode adds `scripts/deck_sources.py`, `scripts/meta_sources.py`, and
`scripts/audit_compare.py`.

> **User-facing guide:** see [`README.md`](README.md) for install, quick start, and troubleshooting. Config authoring walkthrough at [`references/config-walkthrough.md`](references/config-walkthrough.md). Audit methodology: [`references/audit-guide.md`](references/audit-guide.md).

## Mode Selection

Decide before intake:

| The user… | Mode |
|---|---|
| Asks for a deck, names a commander with no list, wants to start fresh | **Build** |
| Supplies a decklist, deck URL, or asks what to change about an existing deck | **Audit** |
| Supplies a deck *and* asks for a rebuild | **Audit first**, then offer targeted swaps |
| Asks how a deck compares to the meta, or whether a list is optimal | **Audit** |

Auditing before rebuilding matters: a full rebuild discards the pilot's tuning,
card availability, and playgroup context. Most decks that arrive for review are
already close to correct and need a handful of swaps, not a new list. Offer the
rebuild only after showing that the list is far from the consensus core.

Say which mode you are entering in one line, then proceed. Do not run build-mode
intake questions on a user who handed you a deck.

## Sub-Agent Dispatch Guardrail

Every build-pipeline step MUST be a separate sub-agent invocation — never
inlined. Challengers must not share context with the primary they review.
Details and rationale: [`references/build-pipeline.md`](references/build-pipeline.md).

## Configuration (.mtg-commander.yml)

At pipeline start, read `.mtg-commander.yml` from the working directory if present.

**If absent:** use all defaults and note once: `No .mtg-commander.yml found — using defaults.`

**If present:** apply recognized keys, use defaults for missing ones, and warn on
invalid or unrecognized keys — but never fail a run over config. An invalid YAML
file warns and falls back to all defaults.

The full schema, defaults, and validation rules live in
[`references/config-schema.md`](references/config-schema.md). Load that file when
the user asks about configuration or needs non-default behavior. In audit mode
the `audit` block sets the tournament-data window (`period`, `min_event_size`),
how many top decklists to diff (`top_decks`), and the new-card cutoff
(`new_card_since`).

---

## Scripts

All network access goes through stdlib-only Python scripts run in the shell —
no WebFetch allowlist or domain permissions needed, nothing to install.
`${SKILL_DIR}` is the skill folder containing this `SKILL.md`; resolve it to an
absolute path before running anything.

| Script | Hosts | Notes |
|---|---|---|
| `card_lookup.py` | api.scryfall.com, archidekt.com | Scryfall requires both `User-Agent` and `Accept` headers |
| `deck_sources.py` | api2.moxfield.com, archidekt.com, r.jina.ai | Moxfield is Cloudflare-protected; Jina reader is a fallback for public/unlisted decks |
| `meta_sources.py` | cedhstats.org, edhtop16.com | HTML scrapers; parsers degrade to warnings rather than crashing |
| `audit_compare.py` | api.scryfall.com | Paginated bulk queries plus a printing cache under `~/.cache/mtg-commander/` |

Scryfall rate-limits aggressively. The audit scripts pace requests and back off
on 429, but do not run concurrent audits — they starve each other.

**Card data (both modes)**

```
python ${SKILL_DIR}/scripts/card_lookup.py validate --name "Sol Ring"
python ${SKILL_DIR}/scripts/card_lookup.py search --query "oracle:sacrifice type:creature id:B legal:commander"
python ${SKILL_DIR}/scripts/card_lookup.py batch --names "Sol Ring" "Dark Ritual"
python ${SKILL_DIR}/scripts/card_lookup.py price --name "Sol Ring"
python ${SKILL_DIR}/scripts/card_lookup.py batch-price --names "Sol Ring" "Dark Ritual"
python ${SKILL_DIR}/scripts/card_lookup.py ck-batch-price --names "Sol Ring" "Dark Ritual"
python ${SKILL_DIR}/scripts/card_lookup.py random-commander --colors BG --strategy sacrifice
python ${SKILL_DIR}/scripts/card_lookup.py validate-deck --commander "Karlov of the Ghost Council" \
    --partner "Second Commander" --cards "Sol Ring" "Dark Ritual"
```

**Audit mode** adds `deck_sources.py`, `meta_sources.py`, and `audit_compare.py`.
Each emits JSON and keeps deck boards separate — never flatten commanders,
mainboard, and maybeboard into one list. Invocations are in
[Audit Steps](#audit-steps) below; `python <script> --help` lists every flag.

---

## Build Mode

When the user asks for a new deck, read
[`references/build-pipeline.md`](references/build-pipeline.md). It contains the
intake flow, the four agent prompt templates, challenger specs, the adversarial
loop protocol, correction cycles, and the final output format.

**Read it only when building.** Audit requests do not need it, and loading it
costs context you would rather spend on the deck.

Two things from build mode are worth knowing up front, because they shape how
you respond in either mode:

- **Every pipeline step is a separate sub-agent.** Eight dispatches: four
  primaries plus four challengers. Running a step inline destroys adversarial
  independence — see the guardrail above.
- **The build pipeline needs a complete 100-card result.** If you cannot reach
  Scryfall, say so and stop rather than inventing card data.

## Audit Mode

Audit mode evaluates a deck that already exists. It is lighter than the build
pipeline: three scripted data steps, then analysis. Load
[`references/audit-guide.md`](references/audit-guide.md) before starting — it
defines the evidence hierarchy, the reporting format, and the rules for what
not to recommend cutting.

### Audit intake

Extract what you can from the message; ask only for what is missing.

| Input | Source | Default |
|---|---|---|
| Deck | URL, pasted list, or file | Required |
| Goal | The user's own words ("top cut a 10K", "beat my local meta") | General optimization |
| Time window | Explicit, or infer from goal | `ONE_YEAR`; `THREE_MONTHS` if the goal is about the current meta |
| Event size floor | Explicit, else infer | `0` (all). Use `50` for serious competitive goals |
| Budget | Explicit | None (report prices, don't filter) |
| Scope | `full`, `new-cards`, `mana`, `interaction` | `full` |

Confirm in one line, then run. Audit intake is deliberately short — the user
already has a deck and wants an answer, not a questionnaire.

### Audit steps

**1. Ingest.** Keep boards separate.

```bash
python ${SKILL_DIR}/scripts/deck_sources.py moxfield --id <id>
python ${SKILL_DIR}/scripts/deck_sources.py archidekt --id <id>
python ${SKILL_DIR}/scripts/deck_sources.py file --path <path>
```

If `deck_total` is not 100, stop and resolve it. If `warnings` reports
multiple copies outside basics or no commanders, surface that before analysis.

**2. Tournament data.** Pass both names for partner pairs.

```bash
python ${SKILL_DIR}/scripts/meta_sources.py cedhstats --commanders "<A>" "<B>"
python ${SKILL_DIR}/scripts/meta_sources.py edhtop16 --commanders "<A>" "<B>" \
    --period ONE_YEAR --min-size 0 --top-decks 8
```

If either site returns `error`, say so plainly and continue with what you have.
Never present an empty result as "no data exists" — distinguish "site had no
record" from "fetch failed."

**3. Compare.**

```bash
python ${SKILL_DIR}/scripts/audit_compare.py \
    --deck deck.json --cedh cedh.json --edhtop edh.json --since <YYYY-MM-DD>
```

`--since` should be 12–18 months back unless the user asks for a shorter new-card
window. Quote these tables rather than recomputing figures in prose.

**4. Analyze and report.** Follow `references/audit-guide.md` §6–§9:

- Classify: tune (≥60 of 100 cards in the top-list core), rework (40–59), or
  rebuild (<40).
- Rank cuts by evidence against, then apply the do-not-cut overrides.
- Pair each cut with an add and a **mechanical** reason.
- Separate high-confidence swaps from tests.
- Screen new cards by first printing and report adoption honestly.
- State sample sizes, filters, and the pull date.

### Audit output

Use the report structure in `references/audit-guide.md` §9. Do not emit the
build pipeline's game-plan/category/price sections — an audit's deliverable is
a swap sheet and the reasoning behind it.

If the user wants the audit written up for later use, write a Markdown file into
the working directory with a header naming all three data sources and the pull
date.

### Audit guardrails

- Never recommend a cut without naming the replacement and the reason.
- Never merge maybeboard or sideboard cards into the deck.
- Never cite a percentage you did not get from the scripts.
- Never apply cEDH tournament data to a bracket 1–3 deck; run structural checks
  only and say why.
- If the user's deck is already well-positioned, say so. "Six swaps and you're
  current" is a complete and useful answer.

---

## Conversational Tone

Talk like a knowledgeable playtest partner, not a report generator.

- Ask conversationally: "Which colors do you want to play?" — not "Specify color identity parameter."
- Confirm briefly: "Commander confirmed." — not "Validation complete: status SUCCESS."
- Fail constructively: "Card not found — did you mean…?"
- Explain mechanically: "Triggers Blood Artist on each sacrifice," not just a stat line.

**Do not surface to the user:** internal agent template names, PRD requirement
numbers, raw API responses, or pipeline config values. Name a synergy category
only in context ("5 interactions, mostly Triggers and Feeds").
