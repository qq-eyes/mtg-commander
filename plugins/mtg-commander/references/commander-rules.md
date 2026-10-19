# Commander Format Rules

Reference document for the Rules Judge agent. This is the authoritative source for format legality validation within the MTG Commander Deck Builder pipeline.

---

## Format Overview

Commander (also known as EDH -- Elder Dragon Highlander) is a multiplayer Magic: The Gathering format built around a legendary creature that defines your deck's identity.

---

## Core Rules

### Deck Construction

| Rule | Specification |
|------|--------------|
| Deck size | Exactly 100 cards (including the commander) |
| Singleton | No more than one copy of any card, except basic lands (Plains, Island, Swamp, Mountain, Forest) |
| Commander | Must be a Legendary Creature, or a card that explicitly states "can be your commander" (e.g., some Planeswalkers) |
| Color identity | Every card in the deck must fall within the commander's color identity |
| Starting life | 40 |
| Players | Typically 3-4 (multiplayer), but 1v1 is also played |

### Color Identity

Color identity is determined by ALL mana symbols appearing on a card -- not just its casting cost. This includes:

- Mana symbols in the mana cost
- Mana symbols in the rules text (e.g., activated abilities)
- Color indicator (the dot on the type line of some cards)
- Both faces of double-faced cards

**Color identity is NOT determined by:**
- Reminder text (text in parentheses)
- Color words in rules text (e.g., "target black creature" does not make a card black)

#### Hybrid Mana

Hybrid mana symbols (e.g., {W/B}) contribute ALL colors in the symbol to the card's color identity. A card with {W/B} in its cost has BOTH white and black in its color identity. This means a mono-white commander deck CANNOT include a card with {W/B} -- the card's identity includes black.

#### Colorless

Colorless cards (identity: {C} or no colored symbols) can go in any deck. Generic mana costs ({1}, {2}, etc.) do not contribute to color identity.

### The Commander Zone

- The commander begins the game in the **command zone**, not in the deck.
- You may cast your commander from the command zone.
- **Commander tax**: Each time you cast your commander from the command zone beyond the first, it costs an additional {2} for each previous time it was cast from the command zone that game.
- When your commander would be put into your graveyard, exile, hand, or library from anywhere, you may choose to put it into the command zone instead.

### Commander Damage

- If a single commander deals 21 or more **combat damage** to a single player over the course of the game, that player loses the game.
- Commander damage is tracked per commander, per player.
- Only combat damage counts -- damage from abilities or spells cast by the commander does NOT count toward the 21.

### Mulligan Rules

Commander uses a **free first mulligan**:
1. Each player draws 7 cards.
2. Each player may take one free mulligan (draw 7 again, no penalty).
3. Subsequent mulligans follow the London Mulligan rule: draw 7, then put N cards on the bottom of your library (where N is the number of mulligans taken after the free one).

---

## Partner Commanders

Some commanders have the **Partner** keyword, allowing a player to have two commanders. Partner decks have special rules:

- Both commanders start in the command zone.
- The deck is still exactly 100 cards (including both commanders, so 98 other cards).
- The deck's color identity is the COMBINED color identity of both commanders.
- Commander tax is tracked separately for each partner.
- Commander damage is tracked separately for each partner.

### Supported Partner Variants

All partner variants are supported. Detection: check the `keywords` array in
Scryfall card data for "Partner", "Partner with", "Choose a Background", or
"Friends forever" (Backgrounds themselves carry "Choose a Background" in their
text rather than the keyword array — validate a Background by checking its type
line for "Background").

| Variant | Pairing rule | Notes |
|---|---|---|
| **Partner** | Any two cards with Partner | e.g. Rograkh + Thrasios, Tymna + Kraum |
| **Partner with <name>** | Fixed pair only | e.g. "Partner with X" must pair with X |
| **Choose a Background** | Commander + one Background enchantment | Background is the second commander, not part of the 98 |
| **Friends forever** | Any two cards with Friends forever | Doctor Who pairs |
| **Doctors companion** | Doctor + one companion-type card | Same slot accounting |

**Construction rules for every variant:**

- The deck is still exactly **100 cards**, including both commanders — so the
  mainboard is **98 cards**, not 99.
- Color identity is the **union** of both commanders' identities. A card is
  legal if its identity is a subset of that union.
- Commander tax and commander damage are tracked **separately** per commander.
- The singleton rule applies across the whole deck; the two commanders are the
  only "duplicates" if they somehow share a name (they cannot).
- A Background/companion-type second commander still occupies a commander slot,
  not a mainboard slot.

**Audit mode:** the pair defines the tournament-data lookup. Both names go to
`meta_sources.py --commanders`. EDHTop16 stores one canonical ordering per pair
and returns HTTP 500 for the reverse order; try both before concluding the pair
has no data. cedhstats slugs join the two names, e.g. `rograkh-thrasios`.

---

## Companion Rule (for reference)

The Companion mechanic exists in Commander but has a modified rule: the companion requirement must be met by all 100 cards in the deck (including the commander). The companion occupies a special slot outside the 100-card deck. This plugin does not actively manage companions in v1 but does not prevent companion-legal cards from appearing in the deck.

---

## Format Legality

A card is legal in Commander if:
1. It is not on the Commander banned list (see `banned-list.md`)
2. Scryfall reports `legalities.commander: "legal"` for the card
3. It is a tournament-legal Magic card (no silver-bordered, playtest, or acorn-stamped cards unless house-ruled)

The Rules Judge validates legality using Scryfall's `legalities.commander` field as the authoritative source.

---

## Basic Lands Reference

The following are the 5 basic land types that are exempt from the singleton rule:

| Basic Land | Color Produced |
|-----------|---------------|
| Plains | {W} (White) |
| Island | {U} (Blue) |
| Swamp | {B} (Black) |
| Mountain | {R} (Red) |
| Forest | {G} (Green) |

Snow-covered basics (Snow-Covered Plains, etc.) and Wastes are also basic lands exempt from singleton.
