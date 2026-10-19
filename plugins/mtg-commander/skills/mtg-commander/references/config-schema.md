# `.mtg-commander.yml` Schema (version 1)

Reference for the configuration file. The skill reads this schema at pipeline
start; load this file when the user asks about configuration, or when a run
needs non-default loop caps, price rules, or escalation behavior.

`references/config-walkthrough.md` explains each setting in prose. This file is
the normative schema and validation rules.

### Schema (version 1)

```yaml
version: 1                    # schema version — required for future migrations
loops:
  deck_builder: 2             # max adversarial loop iterations for Deck Builder/Challenger
  rules_judge: 2              # max adversarial loop iterations for Rules Judge/Challenger
  optimizer: 2                # max adversarial loop iterations for Optimization/Challenger
  price_evaluator: 2          # max adversarial loop iterations for Price/Challenger
correction:
  max_cycles: 3               # max Deck Builder correction cycles per pipeline run (default 3)
price_rules:
  max_card_price: null         # soft per-card goal in USD; null = no goal (15% hard cap still applies)
  escalation: true             # true = escalate unsubstitutable over-goal cards to user; false = auto-substitute silently
  budget_source: higher        # higher | tcgplayer | cardkingdom — which vendor total to use for budget check
escalation:
  on_loop_exhaustion: warn     # warn | block | best-effort — behavior when adversarial loop cap is reached without PASS
audit:
  period: ONE_YEAR             # ONE_MONTH | THREE_MONTHS | SIX_MONTHS | ONE_YEAR — EDHTop16 window
  min_event_size: 0            # 0 = all events; 50 for serious competitive analysis
  top_decks: 8                 # top-finishing decklists to diff against
  new_card_since: null         # YYYY-MM-DD first-printing cutoff; null = 12 months back
```

### Defaults

All keys above show their default values. Missing file = all defaults. Partial file = stated values override defaults, unstated keys use defaults. Unknown keys = warned and ignored.

### Validation Rules

- `version` must be `1` (integer). Other values: warn, use defaults.
- `loops.*` must be positive integers >= 1. Invalid: warn, use default (2).
- `price_rules.max_card_price` must be null or a positive number. Invalid: warn, use null.
- `price_rules.escalation` must be boolean. Invalid: warn, use true.
- `price_rules.budget_source` must be one of `higher`, `tcgplayer`, `cardkingdom`. Invalid: warn, use `higher`.
- `escalation.on_loop_exhaustion` must be one of `warn`, `block`, `best-effort`. Invalid: warn, use `warn`.
- `correction.max_cycles` must be a positive integer >= 1. Invalid: warn, use default (3).
- `audit.period` must be one of `ONE_MONTH`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`. Invalid: warn, use `ONE_YEAR`.
- `audit.min_event_size` must be a non-negative integer. Invalid: warn, use 0.
- `audit.top_decks` must be a positive integer <= 20. Invalid: warn, use 8.
- `audit.new_card_since` must be null or a `YYYY-MM-DD` date. Invalid: warn, use null.
