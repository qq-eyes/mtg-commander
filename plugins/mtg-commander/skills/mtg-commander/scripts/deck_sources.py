#!/usr/bin/env python3
"""Deck ingestion for MTG Commander audit workflows.

Fetches decklists from Moxfield, Archidekt, or a local text file and emits a
normalized JSON document with **boards kept separate**. Board separation is the
whole point of this script: mainboard, maybeboard, and commander cards must
never be merged, or analysis will describe considering-list cards as if they
were in the deck.

stdlib only — no pip dependencies. JSON to stdout.

Usage:
    python deck_sources.py moxfield --id ExampleDeck000000000000
    python deck_sources.py moxfield --url https://moxfield.com/decks/ExampleDeck000000000000
    python deck_sources.py archidekt --id 1234567
    python deck_sources.py archidekt --url https://archidekt.com/decks/1234567/example-deck
    python deck_sources.py file --path deck.txt
    python deck_sources.py file --path -            # read stdin

Output shape:
    {
      "source": "moxfield",
      "name": "...",
      "url": "...",
      "last_updated": "...",
      "boards": {
        "commanders": [{"quantity": 1, "name": "...", "set": "...", "released_at": "..."}],
        "mainboard":  [...],
        "maybeboard": [...],
        "sideboard":  [...]
      },
      "counts": {"commanders": 2, "mainboard": 98, "deck_total": 100},
      "warnings": [...]
    }

`deck_total` counts commanders + mainboard only. Maybeboard and sideboard never
count toward the 100.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "mtg-commander-skill/2.0 (deck audit)"
TIMEOUT = 45


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get(url: str, *, accept: str = "application/json", retries: int = 2) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
    raise RuntimeError(f"GET failed: {url}: {last_exc}")


def _get_json(url: str, *, accept: str = "application/json") -> dict:
    return json.loads(_get(url, accept=accept).decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Moxfield
# ---------------------------------------------------------------------------

_MOXFIELD_ID = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_-]+)")
_MOXFIELD_API = "https://api2.moxfield.com/v3/decks/all/{id}"

# Moxfield sits behind Cloudflare and returns a JS challenge to many clients.
# The Jina reader proxy fetches the API URL server-side and returns the raw JSON
# body. Use it only as a fallback; it is a third-party service, so the deck must
# already be public or unlisted (not private) for this to work at all.
_JINA_PREFIX = "https://r.jina.ai/"


def _moxfield_payload(deck_id: str) -> dict:
    url = _MOXFIELD_API.format(id=deck_id)
    try:
        raw = _get(url)
        text = raw.decode("utf-8", "replace").lstrip()
        if text.startswith("{"):
            return json.loads(text)
    except RuntimeError:
        pass

    proxied = _get(_JINA_PREFIX + url, accept="text/plain").decode("utf-8", "replace")
    start = proxied.find('{"id"')
    if start < 0:
        raise RuntimeError(
            "Moxfield returned a Cloudflare challenge and the Jina fallback did "
            "not contain JSON. Ask the user to paste the decklist or export it."
        )
    return json.loads(proxied[start:])


def fetch_moxfield(deck_id: str) -> dict:
    payload = _moxfield_payload(deck_id)

    board_map = {
        "commanders": "commanders",
        "mainboard": "mainboard",
        "sideboard": "sideboard",
        "maybeboard": "maybeboard",
        "companions": "companions",
        "signatureSpells": "signatureSpells",
    }
    boards: dict[str, list] = {v: [] for v in board_map.values()}

    for src_name, dst_name in board_map.items():
        cards = (payload.get("boards", {}).get(src_name, {}) or {}).get("cards", {}) or {}
        for entry in cards.values():
            card = entry.get("card", {}) or {}
            boards[dst_name].append({
                "quantity": entry.get("quantity", 1),
                "name": card.get("name", ""),
                "set": card.get("set", ""),
                "set_name": card.get("set_name", ""),
                "released_at": None,  # filled by the caller via Scryfall if needed
                "scryfall_id": card.get("scryfall_id"),
            })

    return {
        "source": "moxfield",
        "name": payload.get("name", ""),
        "url": payload.get("publicUrl") or f"https://moxfield.com/decks/{deck_id}",
        "last_updated": payload.get("lastUpdatedAtUtc"),
        "bracket": payload.get("bracket"),
        "visibility": payload.get("visibility"),
        "boards": boards,
    }


# ---------------------------------------------------------------------------
# Archidekt
# ---------------------------------------------------------------------------

_ARCHIDEKT_ID = re.compile(r"archidekt\.com/decks/(\d+)")
_ARCHIDEKT_API = "https://archidekt.com/api/decks/{id}/"


def fetch_archidekt(deck_id: str) -> dict:
    payload = _get_json(_ARCHIDEKT_API.format(id=deck_id))

    boards: dict[str, list] = {
        "commanders": [], "mainboard": [], "maybeboard": [],
        "sideboard": [], "companions": [], "signatureSpells": [],
    }

    for entry in payload.get("cards", []) or []:
        card = entry.get("card", {}) or {}
        oracle = card.get("oracleCard", {}) or {}
        name = oracle.get("name") or card.get("displayName") or ""
        cats = [c.lower() for c in (entry.get("categories") or [])]

        if entry.get("companion"):
            board = "companions"
        elif "commander" in cats:
            board = "commanders"
        elif "maybeboard" in cats or "considering" in cats:
            board = "maybeboard"
        elif "sideboard" in cats:
            board = "sideboard"
        else:
            board = "mainboard"

        edition = card.get("edition", {}) or {}
        boards[board].append({
            "quantity": entry.get("quantity", 1),
            "name": name,
            "set": (edition.get("editioncode") or "").upper(),
            "set_name": edition.get("editionname", ""),
            "released_at": edition.get("editiondate") or card.get("releasedAt"),
            "scryfall_id": oracle.get("uid"),
        })

    return {
        "source": "archidekt",
        "name": payload.get("name", ""),
        "url": f"https://archidekt.com/decks/{deck_id}",
        "last_updated": payload.get("updatedAt"),
        "bracket": payload.get("edhBracket"),
        "visibility": "private" if payload.get("private") else "public",
        "boards": boards,
    }


# ---------------------------------------------------------------------------
# Text decklists
# ---------------------------------------------------------------------------

# Section headers seen in Moxfield / Archidekt / MTGO exports.
_HEADER_PATTERNS = [
    (re.compile(r"^\s*(commanders?|commander)\s*$", re.I), "commanders"),
    (re.compile(r"^\s*(mainboard|main deck|deck|main)\s*$", re.I), "mainboard"),
    (re.compile(r"^\s*(sideboard)\s*$", re.I), "sideboard"),
    (re.compile(r"^\s*(maybeboard|considering|maybe)\s*$", re.I), "maybeboard"),
    (re.compile(r"^\s*(companions?)\s*$", re.I), "companions"),
    (re.compile(r"^\s*(tokens?)\s*$", re.I), "tokens"),
]

_LINE = re.compile(r"^\s*(\d+)\s*[xX]?\s+(.+?)\s*(?:\([A-Za-z0-9]+\)\s*\d*)?\s*(?:\*[A-Z]+\*)?\s*$")
_COMMENT = re.compile(r"^\s*(//|#)\s*(.*)$")


def parse_text_deck(text: str) -> dict:
    boards: dict[str, list] = {
        "commanders": [], "mainboard": [], "maybeboard": [],
        "sideboard": [], "companions": [], "tokens": [],
    }
    warnings: list[str] = []
    current = "mainboard"

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        comment = _COMMENT.match(line)
        if comment:
            label = comment.group(2).strip()
            matched = False
            for pattern, board in _HEADER_PATTERNS:
                if pattern.match(label):
                    current = board
                    matched = True
                    break
            if not matched and label:
                warnings.append(f"Unrecognized comment header '{label}' — ignored.")
            continue

        header = False
        for pattern, board in _HEADER_PATTERNS:
            if pattern.match(line):
                current = board
                header = True
                break
        if header or not line.strip():
            continue

        m = _LINE.match(line)
        if not m:
            warnings.append(f"Unparsed line: {raw_line!r}")
            continue

        boards[current].append({
            "quantity": int(m.group(1)),
            "name": m.group(2).strip(),
            "set": "",
            "set_name": "",
            "released_at": None,
            "scryfall_id": None,
        })

    return {
        "source": "text",
        "name": "",
        "url": "",
        "last_updated": None,
        "bracket": None,
        "visibility": None,
        "boards": boards,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Normalize / summarize
# ---------------------------------------------------------------------------

def summarize(deck: dict) -> dict:
    """Add counts and structural warnings. Never merges boards."""

    boards = deck["boards"]
    warnings = list(deck.get("warnings") or [])

    counts = {name: sum(int(c["quantity"]) for c in cards) for name, cards in boards.items()}
    counts["deck_total"] = counts.get("commanders", 0) + counts.get("mainboard", 0)

    if counts.get("commanders", 0) == 0:
        warnings.append(
            "No commander cards found. If this is a text list, add a 'Commander' "
            "header above the commander line."
        )
    elif counts["commanders"] == 1:
        warnings.append("One commander. Confirm it is not a partner/background pair.")
    elif counts["commanders"] == 2:
        warnings.append(
            "Two commander cards found — treating as a partner pair. Color identity "
            "is the union of both."
        )
    elif counts["commanders"] > 2:
        warnings.append(f"{counts['commanders']} commander cards found — expected 1 or 2.")

    if counts["deck_total"] != 100:
        warnings.append(
            f"Commanders + mainboard = {counts['deck_total']}, expected 100. "
            "Confirm the export completed and that maybeboard cards were not counted."
        )

    dupes = {}
    for card in boards.get("mainboard", []):
        if card["quantity"] > 1:
            dupes[card["name"]] = card["quantity"]
    if dupes:
        warnings.append(
            "Multiple copies in mainboard (legal only for basic lands): "
            + ", ".join(f"{n} x{q}" for n, q in sorted(dupes.items()))
        )

    deck["counts"] = counts
    deck["warnings"] = warnings
    return deck


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _deck_id(value: str, pattern: re.Pattern, kind: str) -> str:
    m = pattern.search(value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    raise SystemExit(f"Could not parse {kind} id from: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a Commander decklist and emit normalized JSON with boards separate.",
        prog="deck_sources.py",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_mox = sub.add_parser("moxfield", help="Fetch from Moxfield")
    p_mox.add_argument("--id", help="Deck public id")
    p_mox.add_argument("--url", help="Deck URL")

    p_arc = sub.add_parser("archidekt", help="Fetch from Archidekt")
    p_arc.add_argument("--id", help="Numeric deck id")
    p_arc.add_argument("--url", help="Deck URL")

    p_file = sub.add_parser("file", help="Parse a text decklist")
    p_file.add_argument("--path", required=True, help="Path to file, or - for stdin")

    args = parser.parse_args()

    try:
        if args.command == "moxfield":
            target = args.id or args.url
            if not target:
                raise SystemExit("moxfield requires --id or --url")
            deck = fetch_moxfield(_deck_id(target, _MOXFIELD_ID, "moxfield"))
        elif args.command == "archidekt":
            target = args.id or args.url
            if not target:
                raise SystemExit("archidekt requires --id or --url")
            deck = fetch_archidekt(_deck_id(target, _ARCHIDEKT_ID, "archidekt"))
        else:
            if args.path == "-":
                text = sys.stdin.read()
            else:
                with open(args.path, encoding="utf-8") as fh:
                    text = fh.read()
            deck = parse_text_deck(text)
    except RuntimeError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(2)

    json.dump(summarize(deck), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
