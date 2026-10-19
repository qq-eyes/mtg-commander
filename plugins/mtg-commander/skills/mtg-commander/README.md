# MTG Commander

Build synergy-dense, format-legal, budget-compliant 100-card Commander decks via a multi-agent pipeline — or **audit an existing deck against real tournament data** from EDHTop16 and cedhstats.

> See also: [ARCHITECTURE.md](./ARCHITECTURE.md) — internal design and Mermaid diagrams for contributors. [references/audit-guide.md](./references/audit-guide.md) — audit methodology and reporting format. [NOTICE](./NOTICE) — licensing, modifications, and third-party services.

---

## Two modes

| Mode | Use it when | Deliverable |
|---|---|---|
| **Build** | You want a deck from scratch | A 100-card list with legality, synergy, curve, and pricing |
| **Audit** | You already have a deck and want to know what to change | A swap sheet with evidence, a new-card screen, and a testing plan |

### Audit mode

Hand it a deck URL and ask:

- *"Evaluate my deck against edhtop16 and cedhstats"*
- *"Is this list optimal?"*
- *"What should I swap? I'm interested in new cards from recent sets."*

It will:

1. Pull the list from Moxfield, Archidekt, or a pasted export — **keeping the
   mainboard, maybeboard, and commanders separate**.
2. Fetch the commander's tournament record: cedhstats 6-month card statistics
   (inclusion, lift, PPG deltas with confidence intervals) and EDHTop16 entries,
   conversion, staples, and the top-finishing decklists.
3. Diff your list against the top lists and emit deterministic tables — no
   hand-computed percentages.
4. Report swaps ranked by evidence, screen cards by **first printing** so
   reprints don't masquerade as new designs, and call out cards you should keep
   despite weak average signals.

Audit data is correlational. The skill is instructed to say so, report sample
sizes, and prefer top-list presence over PPG deltas.

> *"It's a dangerous business, going out your door — especially with a stack of 99 cards and a commander. Let me pack your bags properly."* — Bilbo

---

## Quick start

Just ask. The skill triggers on natural phrasing:

- *"Build me a commander deck"*
- *"Build an EDH deck around Karador"*
- *"100-card deck, Golgari sacrifice, $75 budget"*

You'll be asked for up to **7 intake parameters** (any you skip get sensible defaults or inferred from your commander). Once confirmed, the pipeline runs and you get back:

- A categorized 100-card decklist (Commander / Ramp / Card Draw / Removal / Board Wipes / Win Conditions / Synergy Pieces / Lands)
- Format-legality verdict (color identity, banned list, singleton, 100-card count)
- Synergy density score + mana curve
- Dual-vendor pricing (TCGPlayer + Card Kingdom) with a category breakdown
- A plain-text export list, plus purchase links

---

## What it does

Four sub-agents run in sequence, each followed by an independent **Challenger** that re-verifies the primary's work in a clean context:

| Step | Primary | Challenger checks |
|------|---------|-------------------|
| 1 | **Deck Builder** — synergy-first card selection | Challenges weak picks, missed synergies |
| 2 | **Rules Judge** — format legality (color identity, banned, singleton) | Re-runs `validate-deck` programmatically |
| 3 | **Optimization Reviewer** — interaction density, structural minimums, curve | Challenges synergy tags, reviewer blind spots |
| 4 | **Price Evaluator** — budget, per-card cap, dual-vendor pricing | Re-fetches Card Kingdom, flags vendor divergence |

When anything fails, violations route back to the Deck Builder for correction. Sub-agents run independently — no context bleed between agents. Every step is adversarial by design.

---

## Intake parameters

| # | Parameter | Example |
|---|-----------|---------|
| 1 | Color identity | `BG` (Golgari), `WUB` (Esper), `WUBRG` (5-color) |
| 2 | Commander name | `Karador, Ghost Chieftain` |
| 3 | Strategy archetype | `aristocrats`, `voltron`, `tokens`, `lifegain`, `spellslinger` |
| 4 | Power level (1-10) | `6` (focused casual), `8` (high-power), `10` (cEDH) |
| 5 | Meta alignment | `casual`, `mid-power`, `high-power` |
| 6 | Total budget (USD) | `$75`, `$150`, `no budget` |
| 7 | Card restrictions | `no infinite combos`, `must include Sol Ring`, `no card over $10` |

Skip anything you don't care about — the skill infers from your commander or applies defaults.

---

## Pricing & budget

Pricing is **dual-vendor** to catch single-source drift:

- **TCGPlayer** prices via the Scryfall API
- **Card Kingdom** prices via the Archidekt API
- The budget check uses the **higher of the two totals** (conservative default) — a tiebreaker that protects you from buying on CK and finding out prices diverged 50%
- **Per-card soft goal** (optional, via config): tell the skill "stay around $1/card" and the Price Evaluator searches for cheaper functional swaps before asking you to raise the cap
- **CK divergence check**: Price Challenger flags any card where TCG/CK prices diverge by more than 30%, and escalates if the total deck diverges by more than 20%

See `mtg-commander/references/price-evaluator-guide.md` for the full pricing logic.

---

## Config file

Create `.mtg-commander.yml` in your repo (or wherever you invoke the skill) to customize pipeline behavior. Minimal example:

```yaml
version: 1
loops:
  deck_builder: 3        # give the builder 3 correction attempts before escalating
correction:
  max_cycles: 3          # max Deck Builder correction cycles per pipeline run
price_rules:
  max_card_price: 1.00   # soft $1/card goal (hard 15%-of-budget cap still applies)
  escalation: true       # ask before keeping over-goal cards
```

All keys are optional. Missing keys get sensible defaults, invalid keys warn without failing the pipeline.

- A fully commented example lives at `.mtg-commander.yml.example` (see US-3)
- Full schema, defaults, and validation rules are in `mtg-commander/SKILL.md` (section: Configuration)

---

## Example invocation

**You say:**
> Build me a $75 Karador aristocrats deck, $1/card goal, no infinite combos.

**What happens:**

1. The skill validates `Karador, Ghost Chieftain` on Scryfall — legal commander, color identity `WBG`, partner-less
2. Intake confirmed: Karador / WBG / aristocrats / power 6 / casual / $75 / no infinite combos, $1/card goal
3. **Deck Builder** drafts 100 cards — `Phyrexian Altar`, `Viscera Seer`, `Ashnod's Altar`, ramp, draw, removal, lands
4. **Rules Judge** runs `validate-deck` — every card's color identity confirmed inside `WBG`, no banned cards, singleton clean
5. **Optimization Reviewer** scores synergy density, flags any card with fewer than 3 interactions
6. **Price Evaluator** fetches TCG + CK prices, applies the $1/card soft goal, runs the CK divergence check
7. If anything fails, Challengers trigger a correction loop; if it passes, you get the categorized list with purchase links

---

## Troubleshooting

**Card Kingdom prices diverge from TCGPlayer.**
Expected and handled. The Price Challenger flags any card where CK/TCG differ by >30%, and escalates the whole deck if the totals diverge by >20%. Pick which vendor to optimize for when prompted — or set `price_rules.budget_source` in config to pin one.

**The pipeline loops exhaust without passing.**
Check `.mtg-commander.yml` — `escalation.on_loop_exhaustion` controls what happens: `warn` (ship best-effort with a warning), `block` (halt and ask you), or `best-effort` (silent ship). Raising `loops.*` to `3` gives the builder more attempts.

**Your commander got rejected.**
Either a typo (watch for `Did you mean: ...?` suggestions) or the card is on the Commander banned list. Partners, backgrounds, and Friends forever pairs are supported — if you named only half of a pair, the skill will ask for the other half rather than rejecting the deck.

**No prices returned for some cards.**
Cards with no USD price on Scryfall are excluded from budget totals and listed in `UNAVAILABLE_PRICES`. Uncommon for popular cards; more likely for recent un-sets or promos. Verify at your vendor before buying.

**Moxfield returned a Cloudflare challenge.**
Expected on some networks. `deck_sources.py` retries through the Jina reader proxy; if that also fails, export the list from Moxfield and paste it, or point the skill at the `.txt` export.

**An audit says the deck is not 100 cards.**
The export was probably truncated, or maybeboard cards were included in a pasted list. `deck_sources.py` reports `counts.deck_total` separately for commanders + mainboard; check it before trusting the percentages.

**EDHTop16 returned HTTP 500 for a partner pair.**
The site serves one ordering of each pair. `meta_sources.py` tries both automatically. If both fail, that pair has no recorded entries — the audit will say so rather than inventing data.

**Scryfall 429s during a long audit.**
Scryfall rate-limits per client, and `audit_compare.py`'s new-card screen is the heaviest step. It paces requests, honours `Retry-After`, and caches first printings under `~/.cache/mtg-commander/`. Do not run several audits at once.

---

## Reference links

- **Full skill instructions:** [`SKILL.md`](SKILL.md) — the complete pipeline, agent prompts, adversarial loop protocol, and output format
- **Detailed guides** in [`references/`](references/):
  - [`intake-questions.md`](references/intake-questions.md) — full intake question set
  - [`audit-guide.md`](references/audit-guide.md) — audit workflow, evidence hierarchy, report format
  - [`price-evaluator-guide.md`](references/price-evaluator-guide.md) — pricing, budget, CK divergence
  - [`rules-judge-guide.md`](references/rules-judge-guide.md) — format legality checks
  - [`optimizer-guide.md`](references/optimizer-guide.md) — synergy density scoring
  - [`synergy-taxonomy.md`](references/synergy-taxonomy.md) — interaction tags
  - [`archetype-patterns.md`](references/archetype-patterns.md) — strategy templates
  - [`structural-minimums.md`](references/structural-minimums.md) — ramp/draw/removal floors
  - [`banned-list.md`](references/banned-list.md) — current Commander banned list
  - [`commander-rules.md`](references/commander-rules.md) — format rules reference
  - [`build-pipeline.md`](references/build-pipeline.md) — build-mode intake, agent prompts, loops
  - [`audit-guide.md`](references/audit-guide.md) — audit methodology and report format
  - [`config-schema.md`](references/config-schema.md) — `.mtg-commander.yml` schema and validation

---

## Recently fixed

- **DEFECT-001** (closed) — Color identity determinism. Rules Judge + Rules Challenger now use the programmatic `card_lookup.py validate-deck` command. No more LLM-inferred legality calls; every card's color identity is checked against the commander's via the Scryfall API.
- **DEFECT-002** (closed) — Card Kingdom pricing divergence. The Price Challenger fetches CK prices independently via the Archidekt API, flags per-card divergence >30%, and escalates total divergence >20%. Single-vendor budget blind spots are handled.

---

## License and attribution

Copyright 2026 Paul Baker. Licensed under the Apache License, Version 2.0 — see
[`LICENSE.txt`](./LICENSE.txt).

The audit mode, partner-commander support, and the scripts that support them
were added in October 2026; [`NOTICE`](./NOTICE) records exactly what changed.

Third-party services the skill contacts at runtime (no credentials, nothing
bundled): Scryfall, Archidekt, Moxfield, cedhstats, EDHTop16, and the Jina
reader proxy. Magic: The Gathering is a trademark of Wizards of the Coast; this
project is not affiliated with or endorsed by Wizards or any of those services.

---

> *"Go now, and build with a light heart. The road goes ever on — but your deck, at least, will be legal and synergy-dense when you reach the table."* — Bilbo
