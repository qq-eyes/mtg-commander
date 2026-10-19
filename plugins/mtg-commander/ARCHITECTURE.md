# mtg-commander — Architecture

> *Celebrimbor of Eregion writes: eight dispatches, four adversaries, one hundred cards. The forge of this ring is not a single hammer-stroke but a sequence of independent strikes, each tempered by a rival who never saw the first blow fall. So is synergy tested; so is drift caught.*

## Purpose

`mtg-commander/` has two modes sharing one toolkit.

**Build mode** constructs synergy-dense, format-legal, budget-compliant 100-card Commander decklists via a multi-agent pipeline. Four primary agents (Deck Builder, Rules Judge, Optimization Reviewer, Price Evaluator) run sequentially, each paired with an adversarial challenger that re-verifies the primary's work in a clean context. The pipeline self-corrects on failure, escalates on unresolvable conflict, and is tuned per-repo via `.mtg-commander.yml`. Synergy-first card selection is anchored by live Scryfall data; pricing is dual-vendor (TCGPlayer + Card Kingdom) to catch single-source drift.

**Audit mode** evaluates an existing deck against real tournament data. It is deliberately *not* a multi-agent pipeline: the work is dominated by data retrieval and comparison, where determinism matters more than adversarial debate. Three scripts produce the tables; the model's job is interpretation — ranking by an explicit evidence hierarchy, applying do-not-cut overrides, and reporting sample sizes honestly. The audit reference is [`references/audit-guide.md`](references/audit-guide.md).

Partner commanders ("Partner", "Partner with", "Choose a Background", "Friends forever") are supported in both modes: 98 mainboard cards, union color identity, and both names passed to the meta lookup.

Audience of this document: contributors extending the plugin. For user-facing guidance see [`README.md`](README.md).

---

## Components

- **[`SKILL.md`](SKILL.md)** — orchestrator instructions: mode selection, intake flow, audit-mode steps, 4 primary agent prompt templates, 4 challenger agent specs, adversarial loop protocol, correction-cycle routing, and the `.mtg-commander.yml` schema (version 1 with an `audit` block).
- **[`references/`](references/)** — 12 knowledge documents loaded on demand: `archetype-patterns.md`, `synergy-taxonomy.md`, `structural-minimums.md`, `intake-questions.md`, `commander-rules.md`, `banned-list.md`, `rules-judge-guide.md`, `optimizer-guide.md`, `price-evaluator-guide.md`, `api-reference.md`, `config-walkthrough.md`, and `audit-guide.md`.
- **[`scripts/card_lookup.py`](scripts/card_lookup.py)** — stdlib-only Python client for Scryfall (`api.scryfall.com`) and Archidekt (`archidekt.com/api/cards/v2/`); emits JSON. `validate-deck` accepts `--partner`.
- **[`scripts/deck_sources.py`](scripts/deck_sources.py)** — deck ingestion from Moxfield, Archidekt, or text. Emits boards separately; never merges maybeboard into the deck.
- **[`scripts/meta_sources.py`](scripts/meta_sources.py)** — cedhstats and EDHTop16 scrapers. Emits commander summary, per-card inclusion/lift/PPG, staples, entries, and parsed top decklists.
- **[`scripts/audit_compare.py`](scripts/audit_compare.py)** — deterministic comparison engine. Enriches via Scryfall, computes composition, missing core, cut candidates, and a first-printing new-card screen.
- **[`evals/evals.json`](evals/evals.json)** — test prompts for audit and build modes, including regression cases for board bleed and PPG overreach.
- **[`.mtg-commander.yml.example`](.mtg-commander.yml.example)** — template for the user-repo config controlling loop caps, price rules, escalation, and audit defaults.
- **[`NOTICE`](NOTICE)** — copyright holder, a record of the modifications made to the original skill, and the third-party services the scripts contact.

### Diagram 1a — Audit mode (data path)

```mermaid
flowchart TD
    U2([Deck URL or list]) --> DS[deck_sources.py]
    DS -->|boards kept separate| DeckJSON[(deck.json)]
    U2 --> MS[meta_sources.py]
    MS -->|cedhstats| CedhJSON[(cedh.json)]
    MS -->|EDHTop16 + top decks| EdhJSON[(edh.json)]
    DeckJSON --> AC[audit_compare.py]
    CedhJSON --> AC
    EdhJSON --> AC
    AC -. Scryfall enrichment .-> Scry2[Scryfall API]
    AC --> Report[(comparison tables)]
    Report --> Interp[Model interpretation:<br/>evidence hierarchy,<br/>do-not-cut overrides,<br/>sample-size caveats]
    Interp --> Swap([Swap sheet + report])
```

Determinism is the design goal here: every number in the final report comes from
`audit_compare.py`, never from prose arithmetic. That is why audit mode has no
challenger agents — a second model re-deriving percentages would only introduce
drift, whereas the scripts cannot disagree with themselves.

### Diagram 1b — Build mode (component view)

```mermaid
flowchart TD
    User([User]) -->|intake: 7 params| Orch[Orchestrator<br/>SKILL.md]
    Cfg[(.mtg-commander.yml<br/>user repo)] -->|loops, price_rules,<br/>escalation, audit| Orch
    Refs[(references/<br/>12 docs)] -.->|loaded on demand| Orch

    Orch --> P1[1. Deck Builder]
    P1 <-->|adversarial| C1[Deck Challenger]
    P1 --> P2[2. Rules Judge]
    P2 <-->|adversarial| C2[Rules Challenger]
    P2 --> P3[3. Optimization Reviewer]
    P3 <-->|adversarial| C3[Optimization Challenger]
    P3 --> P4[4. Price Evaluator]
    P4 <-->|adversarial| C4[Price Challenger]
    P4 --> Out([100-card deck<br/>+ pricing + rationale])

    P1 -. card_lookup.py .-> Scry[Scryfall API]
    P2 -. validate-deck .-> Scry
    P4 -. batch-price .-> Scry
    P4 -. ck-batch-price .-> Arch[Archidekt API]
    C4 -. ck-batch-price .-> Arch
```

---

## The 4-Agent Pipeline + Adversarial Loop

Pipeline order is strictly sequential: Deck Builder → Rules Judge → Optimization Reviewer → Price Evaluator. Each step is wrapped in a **primary-vs-challenger** loop. The challenger receives only the primary's output artifact + intake params — never the primary's chain-of-thought. If the challenger returns `CHALLENGE`, the orchestrator spawns a **new** primary with the challenger's findings, then a **new** challenger to re-verify. Loop cap defaults to 2 per step (configurable); exhaustion behaviour is governed by `escalation.on_loop_exhaustion`.

### Diagram 2 — One pipeline step (sequence)

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant P1 as Rules Judge<br/>(Primary, spawn #1)
    participant C1 as Rules Challenger<br/>(spawn #2)
    participant P2 as Rules Judge<br/>(Primary, spawn #3)
    participant C2 as Rules Challenger<br/>(spawn #4)

    O->>P1: Task dispatch (deck_state + refs)
    P1-->>O: RULES_JUDGE_VERDICT: PASS
    O->>C1: Task dispatch (verdict artifact only)
    Note over C1: Clean context —<br/>no primary CoT
    C1-->>O: CHALLENGER_VERDICT: CHALLENGE<br/>(3 findings)
    O->>P2: NEW Task dispatch<br/>(findings + deck_state)
    P2-->>O: corrected verdict
    O->>C2: NEW Task dispatch
    C2-->>O: CHALLENGER_VERDICT: PASS
    O->>O: advance to Optimization Reviewer
```

The two primary dispatches (#1, #3) and two challenger dispatches (#2, #4) are **four distinct sub-agent invocations**. This is the anti-inlining guardrail made concrete.

---

## Sub-Agent Dispatch Guardrail

Every pipeline step — primary or challenger — MUST be dispatched as a separate sub-agent. NEVER inline. This is NON-NEGOTIABLE per [`SKILL.md`](SKILL.md) L18-37.

**Why it matters:**

- **Context isolation** — each agent receives only its defined inputs. No prior-agent reasoning bleeds into the next.
- **Adversarial independence** — a challenger sharing context with the primary it reviews cannot meaningfully challenge.
- **Correction-loop integrity** — routing fails if agent boundaries are absent; the correction signal has nothing to travel between.

**Anti-pattern (real session `REDACTED`):** "I'll run the agent roles inline to keep things moving." This collapsed all four agents into a single context window, destroyed adversarial independence, and produced a deck with **14 undetected color identity violations**. The correction loop never fired — there were no boundaries to trigger it. This is the exact failure the guardrail exists to prevent.

---

## Configuration Model (`.mtg-commander.yml`)

User-repo config, placed at the working-directory root. Schema version 1. Missing file → all defaults. Invalid YAML → warn and use defaults (never blocks). Unknown keys → warn and ignore.

### Diagram 3 — Config schema (class)

```mermaid
classDiagram
    class MtgCommanderConfig {
        +int version
        +Loops loops
        +PriceRules price_rules
        +Escalation escalation
    }
    class Loops {
        +int deck_builder
        +int rules_judge
        +int optimizer
        +int price_evaluator
    }
    class PriceRules {
        +float max_card_price
        +bool escalation
        +string budget_source
    }
    class Escalation {
        +string on_loop_exhaustion
    }
    MtgCommanderConfig "1" --> "1" Loops
    MtgCommanderConfig "1" --> "1" PriceRules
    MtgCommanderConfig "1" --> "1" Escalation

    note for Loops "Each field caps adversarial loop iterations per step (default 2)"
    note for PriceRules "max_card_price: soft goal (null=no goal). budget_source in: higher, tcgplayer, cardkingdom"
    note for Escalation "on_loop_exhaustion in: warn, block, best-effort"
```

**Schema defaults** (stripped from the diagram above because Mermaid classDiagram has no syntax for nullable types, enum constraints, or default literals): `version=1`; `loops.deck_builder=2`, `loops.rules_judge=2`, `loops.optimizer=2`, `loops.price_evaluator=2`; `price_rules.max_card_price=null` (no soft goal); `price_rules.escalation=true`; `price_rules.budget_source=higher`; `escalation.on_loop_exhaustion=warn`. The `budget_source` field is effectively an enum constrained to `{higher, tcgplayer, cardkingdom}`; `on_loop_exhaustion` is constrained to `{warn, block, best-effort}` — enforced in config-load validation, not in the diagram.

Config flows into the orchestrator at pipeline start, after intake confirmation and before the pipeline banner. Each loop cap is applied to its corresponding step; `price_rules.max_card_price` becomes a Price Evaluator soft goal (separate from the 15%-of-budget hard cap); `escalation.on_loop_exhaustion` determines fail-mode when a loop exhausts without `PASS`.

---

## Pricing Model

Pricing is **dual-vendor** by design:

- **TCGPlayer** — fetched via Scryfall (`batch-price`).
- **Card Kingdom** — fetched independently via Archidekt (`ck-batch-price`).

**Budget-wins tiebreaker:** when the Price Evaluator fails, budget takes priority over synergy; replaced cards are tagged `[BUDGET_RELAXED]` and the Optimization Reviewer re-evaluates them at a relaxed synergy threshold of 2 (instead of 3).

**CK divergence escalation (DEFECT-002 fix):** the Price Challenger re-fetches CK prices independently and flags per-card divergence > 30% or total divergence > 20% between vendors. This caught a class of bugs where a single-vendor read silently underpriced the deck.

**Per-card goal vs per-card cap — distinct:**

- *Hard cap* — 15% of total budget, always applied.
- *Soft goal* — `price_rules.max_card_price` (optional). Over-goal cards attempt substitution; unsubstitutable cards escalate to the user (or auto-swap silently if `price_rules.escalation: false`).

A card can pass the soft goal but fail the hard cap, or vice versa.

---

## Format Legality Determinism (DEFECT-001 fix)

The Rules Judge MUST use the `validate-deck` programmatic command as the **sole** legality verification mechanism for color identity, banned list, and format legality. See [`scripts/card_lookup.py`](scripts/card_lookup.py) `validate-deck` subcommand.

LLM knowledge of card attributes is unreliable — training data is stale, partial, and prone to confident hallucination. Color identity, ban status, and format legality are deterministic properties of Scryfall records. Every check must go through the API. The Rules Challenger re-runs the same command independently (clean context) and cross-checks 3 random cards via individual `validate` calls to detect systematic drift.

---

## Closed Defects

- **DEFECT-001** — color identity determinism; Rules Judge previously allowed LLM-inferred legality calls. Fix: mandated `validate-deck` programmatic verification. Closed in run `e6f3`.
- **DEFECT-002** — CK divergence; single-vendor pricing allowed silent drift. Fix: independent Archidekt price fetch in the Price Challenger + divergence thresholds (30% per-card, 20% total). Closed in run `e6f3`.

---

## Extension Points

- **Add a new challenger persona** → extend the `## Challenger Agents` section of [`SKILL.md`](SKILL.md); preserve the `CHALLENGER_VERDICT: PASS | CHALLENGE` / `FINDINGS` / `SUMMARY` signal shape so the orchestrator loop can parse it.
- **Add a new pricing source** → add a subcommand to [`scripts/card_lookup.py`](scripts/card_lookup.py) (follow the `ck-batch-price` pattern, Archidekt-style JSON out); document the vendor in [`references/price-evaluator-guide.md`](references/price-evaluator-guide.md); extend `price_rules.budget_source` enum if the vendor should anchor budget checks.
- **Add a new strategy archetype** → extend [`references/archetype-patterns.md`](references/archetype-patterns.md) with the archetype's synergy taxonomy, typical commanders, structural tilts, and commander-recommendation filters.
- **Tune loops / escalation** → user-side only: edit `.mtg-commander.yml` in the invocation directory. No code change needed; the orchestrator reads on every run.

---

## See Also

- [`README.md`](README.md) — user-facing install, quick start, troubleshooting.
- [`references/config-walkthrough.md`](references/config-walkthrough.md) — authoring guide for `.mtg-commander.yml`.
- [`references/price-evaluator-guide.md`](references/price-evaluator-guide.md) — pricing policy, budget-wins rules, escalation formats.
- [`references/rules-judge-guide.md`](references/rules-judge-guide.md) — legality validation checklist and `validate-deck` usage.
