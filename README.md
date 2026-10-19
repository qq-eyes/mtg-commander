# mtg-commander

A Claude Code plugin for Magic: The Gathering Commander / cEDH deck work. Two modes:

- **Build** — construct a 100-card deck from intake parameters, with a four-agent
  pipeline that checks legality, synergy density, mana curve, and price.
- **Audit** — take an existing deck, diff it against real tournament data from
  EDHTop16 and cedhstats, and get a ranked swap sheet with the reasoning.

It handles partner commanders, screens new cards by first printing, and reports
sample sizes honestly instead of passing off correlational numbers as verdicts.

## Install

This repository is a private Claude Code plugin marketplace. Once you've been
given access:

```
/plugin marketplace add qq-eyes/mtg-commander
/plugin install mtg-commander@mtg-tools
```

Restart Claude Code if it doesn't pick the plugin up immediately, then check
`/plugin` to confirm it's enabled.

## Use it

Just talk to it. The skill triggers on natural phrasing:

- *"Build me a cEDH Tymna and Kraum deck"*
- *"Evaluate my deck at https://moxfield.com/decks/… against the meta"*
- *"Is this list optimal? I want new cards from recent sets."*
- *"What should I swap? I'm worried about Rhystic Study."*

For an audit, give it a Moxfield, Archidekt, or EDHTop16 link — or paste an
export. It'll pull the list, fetch the commander's tournament record, and come
back with specific swaps.

## Requirements

- Python 3.10 or newer, standard library only. Nothing to `pip install`.
- Network access to Scryfall, Moxfield, Archidekt, cedhstats, and EDHTop16.

Scryfall rate-limits aggressively. Don't run audits in parallel.

## What's in the box

```
plugins/mtg-commander/
├── plugin.json                 Agent Plugins manifest (ChatGPT / Codex / others)
├── .claude-plugin/plugin.json  Claude Code manifest
├── LICENSE.txt                 Apache 2.0
├── NOTICE                      attribution and modification record
└── skills/mtg-commander/
    ├── SKILL.md                mode selection and audit workflow
    ├── README.md               skill-level documentation
    ├── ARCHITECTURE.md         internal design for contributors
    ├── references/             14 knowledge docs, loaded on demand
    ├── scripts/                4 stdlib-only Python tools
    ├── evals/                  test prompts
    └── LICENSE.txt, NOTICE
```

`SKILL.md` stays under 250 lines so it fits inside the context budget other
agents apply to skills. The build-mode pipeline, config schema, and audit
methodology live in `references/` and load only when a task needs them.

The `references/` and `scripts/` directories are loaded on demand — you don't
need to read them to use the skill.

## Notes

- Deck URLs you feed the skill are sent to the sites it queries. Unlisted decks
  work; private decks do not.
- The Moxfield import has a fallback through a third-party reader proxy when
  Moxfield blocks direct requests. See `NOTICE` for the full list of services
  contacted.
- Magic: The Gathering is a trademark of Wizards of the Coast. Not affiliated
  with or endorsed by Wizards, Scryfall, Moxfield, Archidekt, Topdeck.gg,
  cedhstats, or EDHTop16.

## License

Copyright 2026 Michael Connelly. Modifications Copyright 2026 Paul Baker. Apache License 2.0 — see [`plugins/mtg-commander/LICENSE.txt`](plugins/mtg-commander/LICENSE.txt)
and [`plugins/mtg-commander/NOTICE`](plugins/mtg-commander/NOTICE).
