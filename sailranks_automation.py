#!/usr/bin/env python3
"""Basic SailRanks automation client.

Uses an already-generated SailRanks V2 password hash supplied through
SAILRANKS_PASSWORD_HASH. It does not hash or transform the value.
"""

from __future__ import annotations

import argparse
import base64
import csv
import getpass
import json
import logging
import msvcrt
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("SAILRANKS_BASE_URL", "https://sailranks.com").rstrip("/")
TIMEOUT = float(os.getenv("SAILRANKS_TIMEOUT", "30"))
LOG_FILE = Path(os.getenv("SAILRANKS_LOG_FILE", "sailranks.log"))

SENSITIVE_NAMES = {
    "authorization", "cookie", "set-cookie", "password", "passwd", "pwwd",
    "token", "access_token", "refresh_token", "api_key", "secret",
}


@dataclass
class Player:
    player_id: str
    name: str
    country: str
    sail: str


@dataclass
class ResultRow:
    rank: int
    player_id: str
    name: str
    country: str
    sail: str
    net: str
    total: str
    races: dict[str, str]


def setup_logging() -> None:
    logging.basicConfig(
        filename=LOG_FILE,
        level=os.getenv("SAILRANKS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_NAMES else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", value)
        value = re.sub(r"(?i)(vertx-web\.session=)[^;\s]+", r"\1[REDACTED]", value)
        return value
    return value


def response_body(response: requests.Response) -> Any:
    if "json" in response.headers.get("Content-Type", "").lower():
        try:
            return response.json()
        except ValueError:
            pass
    return response.text


def normalise_url(base_url: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(base_url + "/", path.lstrip("/"))


def parse_id(value: str | int) -> str:
    match = re.search(r"\d+", str(value))
    if not match:
        raise ValueError(f"Could not find a numeric ID in {value!r}")
    return match.group(0)


def player_form_value(value: str | Player) -> str:
    if isinstance(value, Player):
        return f"{value.player_id} - {value.name} - [{value.country}]"
    return value.strip()


def read_lines(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        path = Path(value)
        if path.is_file():
            result.extend(
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        else:
            result.append(value)
    return result


def prompt_for_players(path: str) -> list[str]:
    players = read_lines([path])
    if not players:
        raise ValueError(f"No players found in {path!r}")

    selected: list[str] = []
    print("Enter players one per line. Press Tab to autocomplete; press Enter on a blank line when finished.")
    while True:
        value = prompt_for_player(players).strip()
        if not value:
            return selected
        selected.append(value)


def prompt_for_player(players: list[str]) -> str:
    print("Player: ", end="", flush=True)
    value: list[str] = []
    while True:
        character = msvcrt.getwch()
        if character in ("\r", "\n"):
            print()
            return "".join(value)
        if character == "\003":
            raise KeyboardInterrupt
        if character == "\b":
            if value:
                value.pop()
                print("\b \b", end="", flush=True)
            continue
        if character == "\t":
            prefix = "".join(value).lower()
            match = next(
                (player for player in players if player.lower().startswith(prefix)),
                None,
            )
            if match and match != "".join(value):
                value = list(match)
                print("\rPlayer: " + match, end="", flush=True)
            continue
        if character >= " ":
            value.append(character)
            print(character, end="", flush=True)


class SailRanksClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "sailranks-python-client/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.logger = logging.getLogger("sailranks")

    def url(self, path: str) -> str:
        return normalise_url(self.base_url, path)

    def log_exchange(
        self,
        operation: str,
        method: str,
        request_url: str,
        request_data: Any,
        response: requests.Response,
        started: float,
    ) -> None:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "operation": operation,
            "method": method,
            "url": request_url,
            "request_data": redact(request_data),
            "status_code": response.status_code,
            "response_headers": redact(dict(response.headers)),
            "response_body": redact(response_body(response)),
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
        self.logger.info(json.dumps(record, ensure_ascii=False, default=str))

    def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        request_url = self.url(path)
        started = time.monotonic()
        response = self.session.request(
            method=method,
            url=request_url,
            data=data,
            headers=headers or {},
            timeout=self.timeout,
            allow_redirects=allow_redirects,
        )
        self.log_exchange(operation, method, request_url, data or {}, response, started)
        response.raise_for_status()
        return response

    def open_login(self) -> requests.Response:
        return self.request("GET", "/v/login", operation="open_login")

    def login(self, username: str, password_hash: str) -> requests.Response:
        """Log in using an already-generated SailRanks V2 hash."""
        self.open_login()

        data = {
            "login": username,
            "pwwd": password_hash,
            "referer": "/v/home",
            "version": "V2",
            "formAction": "login",
        }

        response = self.request(
            "POST",
            "/v/login",
            operation="login",
            data=data,
            headers={"Referer": self.url("/v/login")},
        )

        if not login_succeeded(response.text):
            raise RuntimeError(
                "Login was not confirmed. SailRanks returned an unauthenticated page."
            )

        return response

    def create_regatta(
        self,
        name: str,
        category: str,
        format_name: str,
        description: str = "",
        long_description: str = "",
        editor: str = "owner",
    ) -> requests.Response:
        data = {
            "name": name,
            "category": category,
            "format": format_name,
            "description": description,
            "LongDesc": long_description,
            "editor": editor,
            "formAction": "createRegatta",
        }
        return self.request(
            "POST",
            "/v/regattas",
            operation="create_regatta",
            data=data,
            headers={"Referer": self.url("/v/regattas?action=new")},
        )

    def add_players(
        self,
        regatta_id: str | int,
        players: Iterable[str | Player],
        cver: str = "13",
    ) -> requests.Response:
        path = f"/v/regattas/{parse_id(regatta_id)}"
        data = {
            "cver": cver,
            "batchPlayersToAdd": "\n".join(player_form_value(item) for item in players),
            "formAction": "addPlayerToRegatta",
        }
        return self.request(
            "POST",
            path,
            operation="add_players",
            data=data,
            headers={"Referer": self.url(path)},
        )

    def submit_single_race_result(
        self,
        regatta_id: str | int,
        race_id: str | int,
        finishing_entries: Iterable[str],
        dns_entries: Iterable[str] = (),
        cver: str = "14",
        radix: str = "bnmlaaxudq",
    ) -> requests.Response:
        path = f"/v/regattas/{parse_id(regatta_id)}"
        entries = list(finishing_entries)
        dns = list(dns_entries)
        data: dict[str, str] = {
            "cver": cver,
            "raceID": str(race_id),
            "radix": radix,
            "nbEntries": str(len(entries) + len(dns)),
            "formAction": "submitSingleRaceResult",
            "batchDNS": "\n".join(dns),
        }
        for position, entry in enumerate(entries, start=1):
            data[f"{radix}_p{position}"] = entry
        return self.request(
            "POST",
            path,
            operation="submit_single_race_result",
            data=data,
            headers={"Referer": self.url(path)},
        )

    def retrieve_regatta_page(self, regatta_id: str | int) -> requests.Response:
        path = f"/v/regattas/{parse_id(regatta_id)}"
        return self.request(
            "GET",
            path,
            operation="retrieve_regatta_results",
            headers={"Referer": self.url(path)},
        )

    def retrieve_api_page(self, regatta_id: str | int) -> requests.Response:
        path = f"/api/regattas/{parse_id(regatta_id)}"
        return self.request("GET", path, operation="retrieve_regatta_api")

    def get_player(self, player_id: str | int) -> requests.Response:
        return self.request(
            "GET",
            f"/v/players/{parse_id(player_id)}",
            operation="get_player",
        )


def login_succeeded(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True).lower()
    return (
        "login failed" not in page_text
        and (
            "<!-- home -->" in html.lower()
            or soup.find("a", href="/v/manage") is not None
            or soup.find("form", action="/v/logout") is not None
        )
    )


def extract_tabledata(html: str) -> list[dict[str, Any]]:
    match = re.search(
        r"\bvar\s+tabledata\s*=\s*(\[.*?\])\s*;\s*var\s+copydata",
        html,
        re.S,
    )
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError("Found tabledata but could not decode it as JSON") from error


def result_rows(html: str) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for item in extract_tabledata(html):
        races = {
            key: str(value)
            for key, value in item.items()
            if re.fullmatch(r"r\d+|mr", key)
        }
        rows.append(
            ResultRow(
                rank=int(item.get("rank", 0)),
                player_id=str(item.get("_id", "")),
                name=str(item.get("name", "")),
                country=str(item.get("country", "")),
                sail=str(item.get("sail", "")),
                net=str(item.get("totalPoints", "")),
                total=str(item.get("fullPoints", "")),
                races=races,
            )
        )
    return rows


def write_results_csv(rows: Iterable[ResultRow], output: str | Path) -> None:
    rows = list(rows)
    race_names = sorted({race for row in rows for race in row.races})
    fields = ["rank", "player_id", "name", "country", "sail", "net", "total", *race_names]
    with Path(output).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            values = asdict(row)
            values.update(values.pop("races"))
            writer.writerow(values)


def print_results(rows: Iterable[ResultRow]) -> None:
    rows = list(rows)
    if not rows:
        print("No result rows found.")
        return
    race_names = sorted({race for row in rows for race in row.races})
    headers = ["#", "Player", "Sail", "Net", "Total", *race_names]
    table = [headers]
    for row in rows:
        table.append([
            str(row.rank),
            f"{row.name} ({row.country})",
            row.sail,
            row.net,
            row.total,
            *[row.races.get(race, "") for race in race_names],
        ])
    widths = [max(len(str(line[index])) for line in table) for index in range(len(headers))]
    for index, line in enumerate(table):
        print("  ".join(str(value).ljust(widths[column]) for column, value in enumerate(line)))
        if index == 0:
            print("  ".join("-" * width for width in widths))


def credentials_from_dotenv() -> tuple[str, str]:
    username = os.getenv("SAILRANKS_USERNAME")
    password_hash = os.getenv("SAILRANKS_PASSWORD_HASH")
    if not username or not password_hash:
        raise ValueError(
            "Add SAILRANKS_USERNAME and SAILRANKS_PASSWORD_HASH to .env"
        )
    return username, password_hash


def logged_in_client(args: argparse.Namespace) -> SailRanksClient:
    client = SailRanksClient(args.base_url, args.timeout)
    username, password_hash = credentials_from_dotenv()
    client.login(username, password_hash)
    return client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Basic authorised SailRanks automation")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Test login")

    create = sub.add_parser("create-regatta", help="Create a regatta")
    create.add_argument("--name", required=True)
    create.add_argument("--category", required=True)
    create.add_argument("--format", required=True, dest="format_name")
    create.add_argument("--description", default="")
    create.add_argument("--long-description", default="")
    create.add_argument("--editor", default="owner")

    players = sub.add_parser("add-players", help="Add players to a regatta")
    players.add_argument("regatta_id")
    players.add_argument("players", nargs="*")
    players.add_argument("--players-file", default="players.txt")
    players.add_argument("--cver", default="13")

    result = sub.add_parser("submit-result", help="Submit one race result")
    result.add_argument("regatta_id")
    result.add_argument("--race-id", required=True)
    result.add_argument("--finish", action="append", default=[])
    result.add_argument("--dns", action="append", default=[])
    result.add_argument("--cver", default="14")
    result.add_argument("--radix", default="bnmlaaxudq")

    retrieve = sub.add_parser("results", help="Retrieve and parse regatta results")
    retrieve.add_argument("regatta_id")
    retrieve.add_argument("--json", action="store_true")
    retrieve.add_argument("--csv", dest="csv_file")
    retrieve.add_argument("--raw", action="store_true")
    retrieve.add_argument("--api", action="store_true")

    page = sub.add_parser("page", help="Retrieve an authenticated page")
    page.add_argument("path")

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    try:
        client = logged_in_client(args)

        if args.command == "login":
            print("Login completed.")
            return 0

        if args.command == "create-regatta":
            response = client.create_regatta(
                args.name,
                args.category,
                args.format_name,
                args.description,
                args.long_description,
                args.editor,
            )
            print(f"Create request completed: HTTP {response.status_code} {response.url}")
            return 0

        if args.command == "add-players":
            player_values = (
                read_lines(args.players)
                if args.players
                else prompt_for_players(args.players_file)
            )
            if not player_values:
                raise ValueError("At least one player is required")
            response = client.add_players(args.regatta_id, player_values, args.cver)
            print(f"Player request completed: HTTP {response.status_code} {response.url}")
            return 0

        if args.command == "submit-result":
            response = client.submit_single_race_result(
                args.regatta_id,
                args.race_id,
                read_lines(args.finish),
                read_lines(args.dns),
                args.cver,
                args.radix,
            )
            print(f"Result request completed: HTTP {response.status_code} {response.url}")
            return 0

        if args.command == "results":
            response = (
                client.retrieve_api_page(args.regatta_id)
                if args.api
                else client.retrieve_regatta_page(args.regatta_id)
            )
            if args.api or args.raw:
                print(response.text)
                return 0
            rows = result_rows(response.text)
            if args.csv_file:
                write_results_csv(rows, args.csv_file)
                print(f"Wrote {len(rows)} rows to {args.csv_file}")
            elif args.json:
                print(json.dumps([asdict(row) for row in rows], indent=2))
            else:
                print_results(rows)
            return 0

        if args.command == "page":
            response = client.request("GET", args.path, operation="get_page")
            print(response.text)
            return 0

        raise RuntimeError(f"Unhandled command: {args.command}")

    except requests.HTTPError as error:
        print(f"HTTP error: {error}", file=sys.stderr)
        return 1
    except requests.RequestException as error:
        print(f"Network error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
