#!/usr/bin/env python3
"""Deterministic comparison engine for cEDH deck audits.

Takes the outputs of `deck_sources.py` and `meta_sources.py`, enriches every
card through Scryfall, and emits the tables an audit needs. All arithmetic
happens here rather than in prose, so numbers cannot drift between the diff and
the write-up.

Inputs (any of the three tournament inputs may be omitted):
    --deck    JSON from deck_sources.py          (required)
    --cedh    JSON from meta_sources.py cedhstats
    --edhtop  JSON from meta_sources.py edhtop16
    --since   YYYY-MM-DD — screen cards released on/after this date

Usage:
    python audit_compare.py --deck deck.json --cedh cedh.json --edhtop edh.json

Output: one JSON object with:
    composition          land count, curve, type counts, average mana value
    deck_cards           every mainboard/commander card with its tournament signals
    missing_core         staples played by top lists / high-inclusion that the deck lacks
    cuts                 weakest cards by top-list presence, inclusion, and PPG signal
    recent_cards         cards released since --since that appear in the data
    board_warnings       board-placement and count warnings carried from ingestion

Signals are correlational. `ppg_delta` is a difference in tournament points per
game between decks playing the card and decks not playing it; it is not a causal
estimate of the card's strength.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "mtg-commander-skill/2.0 (deck audit)"
SCRYFALL = "https://api.scryfall.com"
TIMEOUT = 60

# Scryfall asks clients to stay under ~10 requests/second and to back off on
# 429. The first-printing screen issues one request per card, which will trip
# the limit without pacing.
_MIN_INTERVAL = 0.12
_last_request = 0.0


def _throttle() -> None:
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


def _scryfall(url: str, *, data: bytes | None = None, retries: int = 6) -> dict:
    """GET/POST with pacing and exponential backoff on 429.

    Collection lookups are the expensive call in this workflow and Scryfall's
    limits are per-client, so a burst from a previous run can still be cooling
    down. Back off generously rather than failing the whole audit.
    """

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"

    delay = 2.0
    for attempt in range(retries + 1):
        _throttle()
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(retry_after) if retry_after else delay
                except ValueError:
                    wait = delay
                time.sleep(min(wait, 30))
                delay = min(delay * 2, 30)
                continue
            raise
    raise RuntimeError(f"Scryfall request failed after retries: {url}")


_PRINTING_CACHE: dict[str, str | None] = {}
_NEW_CARD_SET: set[str] | None = None


def _cache_path() -> str:
    return os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "mtg-commander",
        "new_cards.json",
    )


def _load_cache() -> None:
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            payload = json.load(fh)
            _PRINTING_CACHE.update(payload.get("printings", {}))
            global _NEW_CARD_SET
            if payload.get("new_card_set"):
                _NEW_CARD_SET = set(payload["new_card_set"])
    except (OSError, json.JSONDecodeError):
        pass


def _save_cache(since: str) -> None:
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "since": since,
                "printings": _PRINTING_CACHE,
                "new_card_set": sorted(_NEW_CARD_SET) if _NEW_CARD_SET else [],
            }, fh)
    except OSError:
        pass


def _new_card_names(colors: str, since: str) -> set[str]:
    """Columnar lookup of every card first printed on/after `since`.

    One paginated search beats one request per card by two orders of magnitude
    and keeps the whole screen inside Scryfall's rate limits.
    """

    global _NEW_CARD_SET
    if _NEW_CARD_SET is not None:
        return _NEW_CARD_SET

    query = f"is:firstprinting date>={since} id<={colors} legal:commander"
    url = (
        f"{SCRYFALL}/cards/search?q={urllib.parse.quote(query, safe='')}"
        "&unique=cards&order=released"
    )
    names: set[str] = set()
    pages = 0

    while url and pages < 12:
        try:
            payload = _scryfall(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            break
        for card in payload.get("data", []):
            names.add(card.get("name", ""))
        url = payload.get("next_page")
        pages += 1

    _NEW_CARD_SET = names
    return names


# ---------------------------------------------------------------------------
# Scryfall enrichment
# ---------------------------------------------------------------------------

def _post_identifiers(names: list[str]) -> dict[str, dict]:
    """Look up cards by name, falling back to a DFC's front face.

    Scryfall's collection endpoint rejects full 'A // B' names, so a deck that
    exports 'Growing Rites of Itlimoc // Itlimoc, Cradle of the Sun' would come
    back unresolved and silently drop out of composition counts. Retry those by
    front face and index the result under the original name.
    """

    found: dict[str, dict] = {}
    unresolved: list[str] = []

    for i in range(0, len(names), 75):
        chunk = names[i:i + 75]
        body = json.dumps({"identifiers": [{"name": n} for n in chunk]}).encode()
        try:
            payload = _scryfall(f"{SCRYFALL}/cards/collection", data=body)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Scryfall collection lookup failed: {exc.code}") from exc
        for card in payload.get("data", []):
            found[card["name"]] = card
        unresolved.extend(
            item.get("name", "") for item in payload.get("not_found", []) if item.get("name")
        )

    for name in unresolved:
        if "//" not in name:
            continue
        front = name.split("//")[0].strip()
        try:
            found[name] = _scryfall(
                f"{SCRYFALL}/cards/named?exact={urllib.parse.quote(front)}"
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue

    return found


def _first_printed(name: str) -> str | None:
    """Earliest printing date, so reprints are not mistaken for new cards."""

    if name in _PRINTING_CACHE:
        return _PRINTING_CACHE[name]

    query = urllib.parse.quote(f'!"{name}"', safe="")
    url = f"{SCRYFALL}/cards/search?q={query}&unique=prints&order=released&dir=asc"
    try:
        payload = _scryfall(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    data = payload.get("data") or []
    result = data[0].get("released_at") if data else None
    _PRINTING_CACHE[name] = result
    return result


def _is_land(card: dict) -> bool:
    if "Land" in (card.get("type_line") or ""):
        return True
    faces = card.get("card_faces") or []
    return any("Land" in (f.get("type_line") or "") for f in faces)


def _card_facts(card: dict) -> dict:
    faces = card.get("card_faces") or []
    oracle = card.get("oracle_text") or " // ".join(
        f.get("oracle_text", "") for f in faces
    )
    mana = card.get("mana_cost") or (faces[0].get("mana_cost", "") if faces else "")
    type_line = card.get("type_line") or " // ".join(
        f.get("type_line", "") for f in faces
    )
    return {
        "name": card.get("name", ""),
        "mana_cost": mana,
        "cmc": float(card.get("cmc") or 0),
        "type_line": type_line,
        "oracle_text": oracle,
        "color_identity": card.get("color_identity", []),
        "set": (card.get("set") or "").upper(),
        "set_name": card.get("set_name", ""),
        "released_at": card.get("released_at"),
        "price_usd": (card.get("prices") or {}).get("usd"),
        "is_land": _is_land(card),
        "keywords": card.get("keywords", []),
        "legal_commander": (card.get("legalities") or {}).get("commander"),
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _deck_names(deck: dict) -> dict[str, int]:
    """Flatten commanders + mainboard only. Maybeboard is never included."""

    out: dict[str, int] = {}
    for board in ("commanders", "mainboard"):
        for card in deck["boards"].get(board, []):
            name = card["name"]
            out[name] = out.get(name, 0) + int(card["quantity"])
    return out


def _top_list_counts(edhtop: dict | None) -> tuple[dict[str, int], int]:
    if not edhtop:
        return {}, 0
    decks = edhtop.get("decks") or []
    counts: dict[str, int] = {}
    for deck in decks:
        for card in deck.get("cards", []):
            counts[card["name"]] = counts.get(card["name"], 0) + 1
    return counts, len(decks)


def _cedh_index(cedh: dict | None) -> dict[str, dict]:
    if not cedh:
        return {}
    return {c["name"]: c for c in cedh.get("cards", [])}


def build_report(deck: dict, cedh: dict | None, edhtop: dict | None, since: str | None) -> dict:
    deck_cards = _deck_names(deck)
    top_counts, top_n = _top_list_counts(edhtop)
    cedh_cards = _cedh_index(cedh)

    all_names = set(deck_cards) | set(top_counts) | set(cedh_cards)
    if edhtop:
        for d in edhtop.get("decks", []):
            all_names.update(c["name"] for c in d.get("cards", []))

    try:
        scry = _post_identifiers(sorted(all_names))
    except RuntimeError as exc:
        return {"error": str(exc)}

    facts = {name: _card_facts(card) for name, card in scry.items()}

    # --- Composition --------------------------------------------------------
    lands = [n for n in deck_cards if facts.get(n, {}).get("is_land")]
    nonlands = [n for n in deck_cards if not facts.get(n, {}).get("is_land")]

    curve: dict[str, int] = {}
    for name in nonlands:
        cmc = facts.get(name, {}).get("cmc", 0)
        bucket = str(int(cmc)) if cmc < 7 else "7+"
        curve[bucket] = curve.get(bucket, 0) + 1
    curve = dict(sorted(curve.items(), key=lambda kv: (kv[0] == "7+", int(kv[0]) if kv[0] != "7+" else 99)))

    avg_cmc = (
        round(sum(facts.get(n, {}).get("cmc", 0) for n in nonlands) / len(nonlands), 2)
        if nonlands else 0
    )

    types: dict[str, int] = {}
    for name in deck_cards:
        tl = facts.get(name, {}).get("type_line", "")
        if "Land" in tl:
            kind = "Land"
        elif "Creature" in tl:
            kind = "Creature"
        elif "Instant" in tl:
            kind = "Instant"
        elif "Sorcery" in tl:
            kind = "Sorcery"
        elif "Artifact" in tl:
            kind = "Artifact"
        elif "Enchantment" in tl:
            kind = "Enchantment"
        elif "Planeswalker" in tl:
            kind = "Planeswalker"
        else:
            kind = "Other"
        types[kind] = types.get(kind, 0) + 1

    # --- Per-card table -----------------------------------------------------
    rows = []
    for name, qty in sorted(deck_cards.items()):
        stat = cedh_cards.get(name)
        f = facts.get(name, {})
        rows.append({
            "name": name,
            "quantity": qty,
            "board": "commanders" if name in {
                c["name"] for c in deck["boards"].get("commanders", [])
            } else "mainboard",
            "mana_cost": f.get("mana_cost", ""),
            "cmc": f.get("cmc"),
            "type_line": f.get("type_line", ""),
            "is_land": f.get("is_land", False),
            "set": f.get("set", ""),
            "released_at": f.get("released_at"),
            "price_usd": f.get("price_usd"),
            "top_lists": top_counts.get(name, 0),
            "top_list_total": top_n,
            "cedh_inclusion_pct": stat["inclusion_pct"] if stat else None,
            "cedh_group": stat["group"] if stat else None,
            "ppg_delta": stat["ppg_delta"] if stat else None,
            "ppg_ci_low": stat["ci_low"] if stat else None,
            "ppg_ci_high": stat["ci_high"] if stat else None,
            "clear_signal": stat["clear_signal"] if stat else False,
            "cedh_lift": stat["lift"] if stat else None,
        })

    # --- Missing core -------------------------------------------------------
    staple_rates: dict[str, float] = {}
    for group in (edhtop.get("staples", {}) if edhtop else {}).values():
        for row in group:
            staple_rates[row["name"]] = max(staple_rates.get(row["name"], 0), row["play_rate_pct"])

    missing = []
    for name, f in facts.items():
        if name in deck_cards:
            continue
        stat = cedh_cards.get(name)
        rate = staple_rates.get(name)
        top = top_counts.get(name, 0)
        inclusion = stat["inclusion_pct"] if stat else None

        # Report if a meaningful share of top lists play it, or the broad field
        # includes it heavily. Thresholds are intentionally conservative.
        if top >= max(2, top_n * 0.25) or (inclusion is not None and inclusion >= 40) or (
            rate is not None and rate >= 40
        ):
            missing.append({
                "name": name,
                "mana_cost": f.get("mana_cost", ""),
                "cmc": f.get("cmc"),
                "type_line": f.get("type_line", ""),
                "set": f.get("set", ""),
                "set_name": f.get("set_name", ""),
                "released_at": f.get("released_at"),
                "price_usd": f.get("price_usd"),
                "top_lists": top,
                "top_list_total": top_n,
                "staple_play_rate_pct": rate,
                "cedh_inclusion_pct": inclusion,
                "cedh_group": stat["group"] if stat else None,
                "ppg_delta": stat["ppg_delta"] if stat else None,
                "ppg_ci_low": stat["ci_low"] if stat else None,
                "ppg_ci_high": stat["ci_high"] if stat else None,
                "clear_signal": stat["clear_signal"] if stat else False,
            })

    # Rank missing cards by a combined signal: top-list presence first, then
    # cedhstats inclusion, so "4 of 5 best lists play it" outranks "popular but
    # unproven".
    missing.sort(key=lambda r: (-(r["top_lists"] or 0), -(r["cedh_inclusion_pct"] or 0)))

    # --- Cut candidates -----------------------------------------------------
    cuts = []
    for row in rows:
        if row["board"] == "commanders":
            continue
        if row["is_land"]:
            continue
        low_top = row["top_lists"] <= max(1, top_n * 0.3)
        low_inc = row["cedh_inclusion_pct"] is not None and row["cedh_inclusion_pct"] <= 35
        neg_ppg = row["ppg_delta"] is not None and row["ppg_delta"] < 0 and row["clear_signal"]
        if low_top or low_inc or neg_ppg:
            cuts.append({
                **{k: row[k] for k in (
                    "name", "mana_cost", "cmc", "type_line", "set", "released_at",
                    "price_usd", "top_lists", "top_list_total", "cedh_inclusion_pct",
                    "cedh_group", "ppg_delta", "ppg_ci_low", "ppg_ci_high", "clear_signal",
                )},
                "reasons": [
                    r for r in (
                        f"only {row['top_lists']}/{top_n} top lists" if low_top else None,
                        f"{row['cedh_inclusion_pct']:.1f}% field inclusion"
                        if low_inc else None,
                        "negative PPG with clear signal" if neg_ppg else None,
                    ) if r
                ],
            })
    cuts.sort(key=lambda r: (r["top_lists"], r["cedh_inclusion_pct"] or 0))

    # --- Recent cards -------------------------------------------------------
    # A card's newest printing is usually a reprint. Use the first printing so
    # the "new cards" screen surfaces genuinely new designs rather than every
    # card that happened to appear in a recent Commander precon.
    recent = []
    if since:
        _load_cache()
        identity = "".join(sorted({
            c for cmd in deck["boards"].get("commanders", [])
            for c in (facts.get(cmd["name"], {}).get("color_identity") or [])
        })) or "GUR"
        new_names = _new_card_names(identity, since)

        for name, f in facts.items():
            # Membership in the first-printing set is authoritative; fall back
            # to the default printing's date only when the bulk query failed.
            if new_names:
                if name not in new_names and name.split(" // ")[0] not in new_names:
                    continue
            elif (f.get("released_at") or "") < since:
                continue
            released = _first_printed(name) or (f.get("released_at") or "")
            stat = cedh_cards.get(name)
            recent.append({
                "name": name,
                "in_deck": name in deck_cards,
                "in_top_list": top_counts.get(name, 0) > 0,
                "top_lists": top_counts.get(name, 0),
                "mana_cost": f.get("mana_cost", ""),
                "type_line": f.get("type_line", ""),
                "oracle_text": f.get("oracle_text", ""),
                "set": f.get("set", ""),
                "set_name": f.get("set_name", ""),
                "released_at": released,
                "price_usd": f.get("price_usd"),
                "cedh_inclusion_pct": stat["inclusion_pct"] if stat else None,
                "ppg_delta": stat["ppg_delta"] if stat else None,
                "ppg_ci_low": stat["ci_low"] if stat else None,
                "ppg_ci_high": stat["ci_high"] if stat else None,
                "clear_signal": stat["clear_signal"] if stat else False,
                "staple_play_rate_pct": staple_rates.get(name),
            })
        _save_cache(since)
        recent.sort(key=lambda r: (-(r["in_deck"]), -(r["top_lists"] or 0), -(r["cedh_inclusion_pct"] or 0), r["name"]))

    return {
        "deck": {
            "source": deck.get("source"),
            "name": deck.get("name"),
            "url": deck.get("url"),
            "last_updated": deck.get("last_updated"),
        },
        "commanders": [c["name"] for c in deck["boards"].get("commanders", [])],
        "composition": {
            "total": sum(deck_cards.values()),
            "mainboard": sum(deck["counts"].values()) - deck["counts"].get("commanders", 0)
            if "counts" in deck else None,
            "lands": len(lands),
            "nonlands": len(nonlands),
            "average_nonland_cmc": avg_cmc,
            "curve": curve,
            "types": types,
            "by_board": deck.get("counts"),
        },
        "tournament_context": {
            "cedhstats": {
                "url": cedh.get("url") if cedh else None,
                "summary": cedh.get("summary") if cedh else None,
                "decklists_parsed": cedh.get("decklists_parsed") if cedh else None,
                "updated": cedh.get("updated") if cedh else None,
            },
            "edhtop16": {
                "url": edhtop.get("url") if edhtop else None,
                "summary": edhtop.get("summary") if edhtop else None,
                "period": edhtop.get("period") if edhtop else None,
                "min_event_size": edhtop.get("min_event_size") if edhtop else None,
                "entries_listed": len(edhtop.get("entries", [])) if edhtop else 0,
                "decks_compared": top_n,
                "decks": [
                    {k: d[k] for k in ("pilot", "tournament", "date", "standing", "players", "record", "url")}
                    for d in (edhtop.get("decks", []) if edhtop else [])
                ],
            },
        },
        "deck_cards": rows,
        "missing_core": missing,
        "cuts": cuts,
        "recent_cards": recent,
        "unresolved_cards": sorted(all_names - set(scry)),
        "warnings": deck.get("warnings", []) + (edhtop.get("warnings", []) if edhtop else []),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare a deck against cEDH tournament data and emit audit tables.",
        prog="audit_compare.py",
    )
    parser.add_argument("--deck", required=True, help="JSON from deck_sources.py")
    parser.add_argument("--cedh", help="JSON from meta_sources.py cedhstats")
    parser.add_argument("--edhtop", help="JSON from meta_sources.py edhtop16")
    parser.add_argument("--since", help="Screen cards released on/after this date (YYYY-MM-DD)")
    args = parser.parse_args()

    with open(args.deck, encoding="utf-8") as fh:
        deck = json.load(fh)
    cedh = None
    if args.cedh:
        with open(args.cedh, encoding="utf-8") as fh:
            cedh = json.load(fh)
    edhtop = None
    if args.edhtop:
        with open(args.edhtop, encoding="utf-8") as fh:
            edhtop = json.load(fh)

    report = build_report(deck, cedh, edhtop, args.since)
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
