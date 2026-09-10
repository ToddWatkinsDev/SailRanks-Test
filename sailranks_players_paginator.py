#!/usr/bin/env python3
"""Download every page of the public SailRanks player list.

The supplied /v/players HTML shows:
- 14551 registered players
- a page containing 200 players
- a POST pagination form with:
    action="/v/players"
    name="xquery" value="e30"
    name="index" value="200"
    name="range" value="200"
    value="next"

This script follows that pagination form until there is no next page, while
saving each page's players in the requested format:

    6743 - Geobro - [GBR]

It does not log in. It requests one public page at a time and waits between
requests to reduce load. Existing player IDs in the output file are skipped.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://sailranks.com/v/players"
DEFAULT_OUTPUT = "players.txt"
DEFAULT_STATE = "players_state.json"
DEFAULT_DELAY = 1.0
DEFAULT_JITTER = 0.0
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class Player:
    player_id: int
    name: str
    country: str

    def formatted(self) -> str:
        return f"{self.player_id} - {self.name} - [{self.country}]"


def normalise(value: str) -> str:
    return " ".join(value.split()).strip()


def extract_player_id(href: str) -> int | None:
    match = re.search(r"/v/players/(\d+)(?:$|[?#])", href)
    return int(match.group(1)) if match else None


def extract_players(html: str) -> list[Player]:
    soup = BeautifulSoup(html, "html.parser")
    players: dict[int, Player] = {}

    for link in soup.select('a[href^="/v/players/"]'):
        player_id = extract_player_id(link.get("href", ""))
        if player_id is None:
            continue

        card = link
        name_node = card.select_one("p.title")
        subtitle_node = card.select_one("p.subtitle")
        name = normalise(name_node.get_text(" ", strip=True)) if name_node else ""
        subtitle = normalise(subtitle_node.get_text(" ", strip=True)) if subtitle_node else ""

        country_match = re.search(r"\b([A-Z]{3})\s+" + str(player_id) + r"\b", subtitle)
        if not country_match:
            continue

        country = country_match.group(1)
        if name:
            players[player_id] = Player(player_id, name, country)

    return list(players.values())


def load_known_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    known: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(\d+)\s+-\s+", line)
        if match:
            known.add(int(match.group(1)))
    return known


def append_players(path: Path, players: list[Player], known_ids: set[int]) -> int:
    new_players = [player for player in players if player.player_id not in known_ids]
    if not new_players:
        return 0

    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for player in sorted(new_players, key=lambda item: item.player_id):
            handle.write(player.formatted() + "\n")
            known_ids.add(player.player_id)
            print(f"NEW {player.formatted()}")
    return len(new_players)


def find_next_form(html: str, current_url: str) -> tuple[str, dict[str, str]] | None:
    """Find the site's POST pagination form and return URL plus form data."""
    soup = BeautifulSoup(html, "html.parser")

    for form in soup.find_all("form", method=lambda value: value and value.lower() == "post"):
        submit = form.find("input", attrs={"name": "index", "value": True})
        next_button = form.find("input", attrs={"type": "submit", "value": re.compile(r"next", re.I)})
        if not submit or not next_button:
            continue

        action = form.get("action") or current_url
        target_url = urljoin(current_url, action)
        data: dict[str, str] = {}
        for field in form.find_all("input"):
            name = field.get("name")
            if name:
                data[name] = field.get("value", "")
        return target_url, data

    return None


def fetch_page(session: requests.Session, url: str, timeout: float) -> requests.Response:
    response = session.get(
        url,
        headers={
            "User-Agent": "sailranks-public-player-sync/0.2",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def fetch_next_page(
    session: requests.Session,
    url: str,
    data: dict[str, str],
    timeout: float,
) -> requests.Response:
    response = session.post(
        url,
        data=data,
        headers={
            "User-Agent": "sailranks-public-player-sync/0.2",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": url,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def save_state(path: Path, state: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"pages_completed": 0, "players_saved": 0, "last_index": 0}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {
            "pages_completed": int(value.get("pages_completed", 0)),
            "players_saved": int(value.get("players_saved", 0)),
            "last_index": int(value.get("last_index", 0)),
        }
    except (OSError, ValueError, TypeError):
        return {"pages_completed": 0, "players_saved": 0, "last_index": 0}


def wait(args: argparse.Namespace) -> None:
    delay = args.delay + random.uniform(0, args.jitter)
    if delay > 0:
        print(f"Waiting {delay:.1f} seconds before the next page request...")
        time.sleep(delay)


def run(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    state_path = Path(args.state)
    known_ids = load_known_ids(output_path)
    state = load_state(state_path)
    session = requests.Session()

    current_url = args.url
    current_html: str | None = None
    pages = 0
    total_new = 0

    while True:
        if current_html is None:
            print(f"GET {current_url}")
            response = fetch_page(session, current_url, args.timeout)
        else:
            print(f"POST {current_url} for next page")
            response = fetch_next_page(session, current_url, next_data, args.timeout)

        current_html = response.text
        players = extract_players(current_html)
        if not players:
            raise RuntimeError("No players found on the current page; stopping safely")

        new_count = append_players(output_path, players, known_ids)
        total_new += new_count
        pages += 1

        next_form = find_next_form(current_html, response.url)
        current_index = 0
        if next_form:
            _, data = next_form
            try:
                current_index = int(data.get("index", "0"))
            except ValueError:
                current_index = 0

        state.update({
            "pages_completed": int(state.get("pages_completed", 0)) + 1,
            "players_saved": len(known_ids),
            "last_index": current_index,
        })
        save_state(state_path, state)

        print(f"Page {pages}: extracted {len(players)}, added {new_count}, total saved {len(known_ids)}")

        if args.once or not next_form or (args.max_pages and pages >= args.max_pages):
            break

        next_url, next_data = next_form
        # Keep the form action as the next request target and carry all hidden
        # values exactly as the page supplied them.
        current_url = next_url
        wait(args)

    print(f"Finished: {pages} page(s), {total_new} new player(s) added")
    print(f"Output: {output_path}")
    print(f"State: {state_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Follow SailRanks public player pagination and save all players"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--jitter", type=float, default=DEFAULT_JITTER)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-pages", type=int, default=0, help="0 means no explicit limit")
    parser.add_argument("--once", action="store_true", help="Fetch only the first page")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.delay < 0 or args.jitter < 0:
        print("--delay and --jitter cannot be negative", file=sys.stderr)
        return 2
    if args.max_pages < 0:
        print("--max-pages cannot be negative", file=sys.stderr)
        return 2
    try:
        return run(args)
    except (OSError, requests.RequestException, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
