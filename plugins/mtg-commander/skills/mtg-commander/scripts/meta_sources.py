#!/usr/bin/env python3
"""Tournament metagame data for cEDH deck audits.

Scrapes the two public cEDH stats sites and emits JSON:

  * cedhstats.org — 6-month decklist-derived card statistics (per-card
    inclusion %, lift, PPG delta, confidence intervals) plus commander summary.
  * edhtop16.com — TopDeck.gg-sourced tournament entries, conversion, staples
    tab, and top-finishing decklists.

Neither site offers a documented public JSON API, so this script parses their
server-rendered HTML. Parsers are deliberately defensive: if a site restyles,
the affected field comes back empty with a warning rather than crashing the
whole audit. Treat every number as a clue, not a verdict.

stdlib only — no pip dependencies. JSON to stdout.

Usage:
    python meta_sources.py cedhstats --commanders "Rograkh, Son of Rohgahh" "Thrasios, Triton Hero"
    python meta_sources.py edhtop16  --commanders "Rograkh, Son of Rohgahh" "Thrasios, Triton Hero"
    python meta_sources.py edhtop16  --commanders "Rograkh, Son of Rohgahh" "Thrasios, Triton Hero" \
                                     --period THREE_MONTHS --min-size 50 --top-decks 8
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "mtg-commander-skill/2.0 (deck audit)"
TIMEOUT = 45
CEDHSTATS = "https://cedhstats.org"
EDHTOP16 = "https://edhtop16.com"


# ---------------------------------------------------------------------------
# HTTP / HTML helpers
# ---------------------------------------------------------------------------

def _get(url: str, *, retries: int = 2) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise RuntimeError(f"GET failed: {url}: {last}")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _num(value: str) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(m.group()) if m else None


def _strip_scripts(page: str) -> str:
    return re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)


# ---------------------------------------------------------------------------
# cedhstats
# ---------------------------------------------------------------------------

def _cedhstats_slug(commanders: list[str]) -> tuple[str, str] | None:
    """Resolve a commander pair to its cedhstats slug via the site's search."""

    query = " ".join(c.split(",")[0] for c in commanders)
    page = _get(f"{CEDHSTATS}/commanders?q={urllib.parse.quote(query)}")
    wanted = {c.lower() for c in commanders}

    # Result rows carry both a short label and a full title attribute.
    for m in re.finditer(r'href="(/commanders/[^"#?]+)"[^>]*title="([^"]+)"', page):
        slug, title = m.group(1), html.unescape(m.group(2))
        parts = {p.strip().lower() for p in re.split(r"\s/\s", title)}
        if wanted and wanted.issubset(parts) or wanted == parts:
            return slug.lstrip("/"), title

    # Fallback: match by substring in the title.
    for m in re.finditer(r'href="(/commanders/[^"#?]+)"[^>]*title="([^"]+)"', page):
        slug, title = m.group(1), html.unescape(m.group(2)).lower()
        if all(c.split(",")[0].lower() in title for c in commanders):
            return slug.lstrip("/"), html.unescape(m.group(2))

    return None


def _cedh_summary(page: str) -> dict:
    """Pull the labelled summary tiles (Entries, Meta Share, Avg PPG, ...)."""

    out: dict = {}
    # Each tile: a bold value followed by a label div.
    for m in re.finditer(
        r'<div class="text-2xl font-bold[^"]*">\s*([^<]+?)\s*</div>\s*'
        r'<div class="text-xs text-gray-400 mt-1">\s*([^<]+?)\s*(?:<span|</div>)',
        page,
    ):
        value, label = m.group(1).strip(), _text(m.group(2))
        if label:
            out[label] = value

    record = re.search(r"commander-summary-record.*?</div>\s*</div>", page, flags=re.S)
    if record:
        nums = re.findall(r">\s*(\d+)\s*<", record.group(0))
        if len(nums) >= 3:
            out["Record (W-L-D)"] = "-".join(nums[:3])
    return out


def fetch_cedhstats(commanders: list[str]) -> dict:
    resolved = _cedhstats_slug(commanders)
    if not resolved:
        return {
            "source": "cedhstats",
            "error": "commander not found on cedhstats",
            "commanders": commanders,
            "cards": [],
        }
    slug, title = resolved

    summary_page = _get(f"{CEDHSTATS}/{slug}")
    summary = _cedh_summary(summary_page)

    cards_page = _get(f"{CEDHSTATS}/{slug}/cards?show_lands=1")
    cards = _parse_cards_table(cards_page)

    parsed = re.search(r"([\d,]+)\s*</div>\s*<div[^>]*>\s*parsed decklists", cards_page)
    updated = re.search(r"Updated\s+([A-Z][a-z]{2}\s+\d+,\s+\d{4})", cards_page)

    # PPG deltas are rendered as a signed value plus CI bounds in adjacent cells.
    return {
        "source": "cedhstats",
        "url": f"{CEDHSTATS}/{slug}",
        "cards_url": f"{CEDHSTATS}/{slug}/cards",
        "slug": slug,
        "title": title,
        "summary": summary,
        "decklists_parsed": int(parsed.group(1).replace(",", "")) if parsed else None,
        "updated": updated.group(1) if updated else None,
        "cards": cards,
    }


def _parse_cards_table(page: str) -> list[dict]:
    body = re.search(r"<tbody[^>]*>(.*?)</tbody>", page, flags=re.S | re.I)
    if not body:
        return []

    cards: list[dict] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), flags=re.S | re.I):
        name_m = re.search(r'data-card-name="([^"]+)"', row)
        if not name_m:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
        if len(cells) < 8:
            continue

        def cell(i: int) -> str:
            return _text(cells[i])

        ci = re.findall(r'commander-card-ci-col[^"]*"[^>]*data-v="([^"]*)"', row)
        cards.append({
            "name": html.unescape(name_m.group(1)),
            "ppg_delta": _num(cell(1)) if cell(1) != "n/a" else None,
            "ci_low": _num(ci[0]) if len(ci) > 0 and ci[0] else None,
            "ci_high": _num(ci[1]) if len(ci) > 1 and ci[1] else None,
            "lift": cell(4),
            "group": cell(5),
            "inclusion_pct": _num(cell(6)),
            "decklists": cell(7),
            "clear_signal": "Clear" in row,
        })
    return cards


# ---------------------------------------------------------------------------
# EDHTop16
# ---------------------------------------------------------------------------

def _edhtop16_name(commanders: list[str]) -> str:
    """EDHTop16 uses Scryfall names joined with ' / ', in site-defined order."""

    return " / ".join(commanders)


def _edhtop16_fetch(commanders: list[str], period: str, min_size: int) -> tuple[str, str]:
    """Try both partner orders; the site 500s on the reversed order."""

    name = _edhtop16_name(commanders)
    variants = [name]
    if len(commanders) == 2:
        variants.append(" / ".join(reversed(commanders)))

    params = []
    if period:
        params.append(f"timePeriod={urllib.parse.quote(period)}")
    if min_size:
        params.append(f"minEventSize={min_size}")
    suffix = ("?" + "&".join(params)) if params else ""

    last_error = ""
    for variant in variants:
        path = urllib.parse.quote(variant, safe="")
        url = f"{EDHTOP16}/commander/{path}"
        try:
            page = _get(url + suffix)
        except RuntimeError as exc:
            last_error = str(exc)
            continue
        if "Tournament Entries" in page or "Entries" in page:
            return page, variant

    raise RuntimeError(f"EDHTop16 returned no commander page for {variants}: {last_error}")


def _edh_summary(page: str) -> dict:
    out: dict = {}
    m = re.search(r">([\d,]+)<!-- -->\s*Entries", page)
    if m:
        out["entries"] = int(m.group(1).replace(",", ""))
    for label in ("Meta%", "Conversion"):
        m = re.search(r"<!-- -->([\d.]+)%<!-- -->\s*" + re.escape(label), page)
        if m:
            out[label.replace("%", "_pct")] = float(m.group(1))
    return out


_PLAY_RATE = re.compile(
    r"\b(Land|Creature|Instant|Sorcery|Artifact|Enchantment|Planeswalker|Battle)\s+"
    r"Play rate\s+(.*?)(?=\s+(?:Land|Creature|Instant|Sorcery|Artifact|Enchantment|"
    r"Planeswalker|Battle)\s+Play rate|$)",
    re.S,
)


def _parse_staples(page: str) -> dict[str, list[dict]]:
    """Parse the Staples tab: '<type> Play rate <card> <pct> % <card> <pct> % ...'."""

    text = _text(_strip_scripts(page))
    out: dict[str, list[dict]] = {}
    for m in _PLAY_RATE.finditer(text):
        kind, body = m.group(1), m.group(2)
        # Card names are followed by a percentage; names can contain digits and
        # punctuation, so split on the percentage tokens.
        pairs = re.findall(r"(.*?)\s(\d+(?:\.\d+)?)\s*%", body)
        rows = []
        for chunk, pct in pairs:
            name = chunk.strip()
            if name and not name.lower().startswith("play rate"):
                rows.append({"name": name, "play_rate_pct": float(pct)})
        if rows:
            out.setdefault(kind, []).extend(rows)
    return out


# Entry cards are React-rendered, so the markup between anchors is long and
# class-heavy. Anchor on the decklist link, then parse a bounded window: field
# order inside an entry card is pilot -> tournament -> date -> standing/record.
_ENTRY_ANCHOR = re.compile(
    r'href="/tournament/([^"]+)/decklist/([A-Za-z0-9]+)"[^>]*>([^<]*)</a>'
)
_ENTRY_TOURNAMENT = re.compile(r'href="(/tournament/[^"/]+)">([^<]*)</a>')
_ENTRY_DATE = re.compile(
    r"<span[^>]*>\s*([A-Z][a-z]+\s+\d+(?:st|nd|rd|th)?,?\s+\d{4})\s*</span>"
)
_ENTRY_STANDING = re.compile(r">\s*(\d+)(?:st|nd|rd|th)")
_ENTRY_PLAYERS = re.compile(r"(\d+)\s*<!-- -->\s*players")
_ENTRY_RECORD = re.compile(
    r"Wins:\s*<!-- -->(\d+)<!-- -->\s*/\s*Losses:\s*<!-- -->(\d+)<!-- -->"
    r"\s*/\s*Draws:\s*<!-- -->(\d+)"
)


def _parse_entries(page: str) -> list[dict]:
    entries = []
    for m in _ENTRY_ANCHOR.finditer(page):
        # The window must be long enough to clear the class-heavy markup but not
        # so long that it swallows the following entry's fields.
        window = page[m.end(): m.end() + 3000]

        tournament = _ENTRY_TOURNAMENT.search(window)
        date = _ENTRY_DATE.search(window)
        standing = _ENTRY_STANDING.search(window)
        players = _ENTRY_PLAYERS.search(window)
        record = _ENTRY_RECORD.search(window)
        if not (standing and record):
            continue

        entries.append({
            "tournament_slug": m.group(1),
            "decklist_id": m.group(2),
            "pilot": _text(m.group(3)),
            "tournament": _text(tournament.group(2)) if tournament else m.group(1),
            "tournament_slug_parsed": tournament.group(1).lstrip("/").split("/")[-1] if tournament else m.group(1),
            "date": date.group(1) if date else "",
            "standing": int(standing.group(1)),
            "players": int(players.group(1)) if players else None,
            "wins": int(record.group(1)),
            "losses": int(record.group(2)),
            "draws": int(record.group(3)),
            "url": f"{EDHTOP16}/tournament/{m.group(1)}/decklist/{m.group(2)}",
        })
    return entries


_DECK_ITEM = re.compile(
    r'"count":(\d+),"spice":(\d+),"commanderPlayRate":([0-9.eE+-]+),'
    r'"card":\{"id":"[^"]*","name":"([^"]+)","type":"([^"]*)"'
)


def _deck_cards(page: str) -> list[dict]:
    cards = []
    for m in _DECK_ITEM.finditer(page):
        name = json.loads('"' + m.group(4) + '"')  # unescape / etc.
        kind = json.loads('"' + m.group(5) + '"') if m.group(5) else ""
        cards.append({
            "quantity": int(m.group(1)),
            "spice": int(m.group(2)),
            "slot_play_rate": float(m.group(3)),
            "name": name,
            "type": kind,
        })
    return cards


def fetch_edhtop16(commanders: list[str], period: str, min_size: int, top_decks: int) -> dict:
    try:
        page, name = _edhtop16_fetch(commanders, period, min_size)
    except RuntimeError as exc:
        return {"source": "edhtop16", "error": str(exc), "commanders": commanders, "decks": []}

    staples_page = page
    if "Play rate" not in page:
        try:
            staples_page = _get(
                f"{EDHTOP16}/commander/{urllib.parse.quote(name, safe='')}?tab=staples"
                + (f"&timePeriod={urllib.parse.quote(period)}" if period else "")
                + (f"&minEventSize={min_size}" if min_size else "")
            )
        except RuntimeError:
            staples_page = page

    entries = _parse_entries(page)
    result = {
        "source": "edhtop16",
        "url": f"{EDHTOP16}/commander/{urllib.parse.quote(name, safe='')}",
        "commander_name": name,
        "period": period,
        "min_event_size": min_size,
        "summary": _edh_summary(page),
        "staples": _parse_staples(staples_page),
        "entries": entries,
        "decks": [],
        "warnings": [],
    }

    if not entries:
        result["warnings"].append("No tournament entries parsed — page layout may have changed.")

    # Fetch the top-finishing decklists for card-level comparison.
    for entry in entries[: max(0, top_decks)]:
        try:
            deck_page = _get(entry["url"])
        except RuntimeError:
            result["warnings"].append(f"Could not fetch decklist {entry['url']}")
            continue
        cards = _deck_cards(deck_page)
        if not cards:
            result["warnings"].append(f"No cards parsed from {entry['url']}")
            continue
        result["decks"].append({
            "pilot": entry["pilot"],
            "tournament": entry["tournament"],
            "date": entry["date"],
            "standing": entry["standing"],
            "players": entry["players"],
            "record": f"{entry['wins']}-{entry['losses']}-{entry['draws']}",
            "url": entry["url"],
            "cards": cards,
        })

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch cEDH tournament statistics for a commander (pair).",
        prog="meta_sources.py",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, helptext in (
        ("cedhstats", "Fetch cedhstats summary + per-card statistics"),
        ("edhtop16", "Fetch EDHTop16 entries, staples, and top decklists"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--commanders", nargs="+", required=True,
                       help="Commander name(s); pass two for partners")
        if name == "edhtop16":
            p.add_argument("--period", default="ONE_YEAR",
                           choices=["ONE_MONTH", "THREE_MONTHS", "SIX_MONTHS", "ONE_YEAR"],
                           help="Time window (default ONE_YEAR)")
            p.add_argument("--min-size", type=int, default=0,
                           help="Minimum event size (EDHTop16 filter; 0 = all)")
            p.add_argument("--top-decks", type=int, default=8,
                           help="How many top-finishing decklists to fetch (default 8)")

    args = parser.parse_args()

    try:
        if args.command == "cedhstats":
            result = fetch_cedhstats(args.commanders)
        else:
            result = fetch_edhtop16(args.commanders, args.period, args.min_size, args.top_decks)
    except RuntimeError as exc:
        json.dump({"error": str(exc)}, sys.stdout, indent=2)
        print()
        sys.exit(2)

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
