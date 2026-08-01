#!/usr/bin/env python3
"""Validate the directory, refresh GitHub stars, and generate README entries."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "agents.json"
README_PATH = ROOT / "README.md"
START_MARKER = "<!-- BEGIN GENERATED RANKING -->"
END_MARKER = "<!-- END GENERATED RANKING -->"
ALLOWED_INTERFACES = {"CLI", "IDE", "Web", "Desktop", "Autonomous"}
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY_PATTERN = re.compile(
    r"\*\*Last verified:\*\* \d{4}-\d{2}-\d{2} · "
    r"\*\*Minimum at admission:\*\* \d[\d,]* stars · "
    r"\*\*Projects:\*\* \d+"
)


class ValidationError(ValueError):
    """Raised when the directory data or generated README is invalid."""


class RefreshError(RuntimeError):
    """Raised when live GitHub metadata cannot be fetched safely."""


def parse_date(value: str, field: str) -> None:
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} must use YYYY-MM-DD format")
    try:
        dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"{field} is not a valid calendar date") from error


def sort_key(agent: dict[str, Any]) -> tuple[int, str, str]:
    return (-agent["stars"], agent["name"].casefold(), agent["repo"].casefold())


def sort_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(agents, key=sort_key)


def validate_data(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValidationError("data must be a JSON object")

    parse_date(data.get("last_updated"), "last_updated")
    minimum = data.get("minimum_stars")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValidationError("minimum_stars must be a positive integer")

    agents = data.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValidationError("agents must be a non-empty array")

    required = {
        "name",
        "repo",
        "interfaces",
        "license",
        "description",
        "stars",
        "stars_at_addition",
        "added_at",
    }
    seen_names: set[str] = set()
    seen_repos: set[str] = set()

    for index, agent in enumerate(agents, start=1):
        if not isinstance(agent, dict):
            raise ValidationError(f"agent {index} must be an object")
        missing = required - agent.keys()
        if missing:
            raise ValidationError(
                f"agent {index} is missing: {', '.join(sorted(missing))}"
            )

        name = agent["name"]
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValidationError(f"agent {index} has an invalid name")
        name_key = name.casefold()
        if name_key in seen_names:
            raise ValidationError(f"duplicate agent name: {name}")
        seen_names.add(name_key)

        repo = agent["repo"]
        if not isinstance(repo, str) or not REPO_PATTERN.fullmatch(repo):
            raise ValidationError(f"{name} has an invalid GitHub repository")
        repo_key = repo.casefold()
        if repo_key in seen_repos:
            raise ValidationError(f"duplicate repository: {repo}")
        seen_repos.add(repo_key)

        interfaces = agent["interfaces"]
        if (
            not isinstance(interfaces, list)
            or not interfaces
            or any(item not in ALLOWED_INTERFACES for item in interfaces)
            or len(interfaces) != len(set(interfaces))
        ):
            raise ValidationError(f"{name} has invalid or duplicate interfaces")

        license_name = agent["license"]
        if not isinstance(license_name, str) or not license_name.strip():
            raise ValidationError(f"{name} must have a license status")

        description = agent["description"]
        if (
            not isinstance(description, str)
            or len(description) < 20
            or "\n" in description
            or not description.endswith(".")
        ):
            raise ValidationError(f"{name} must have a one-line description ending in a period")

        stars = agent["stars"]
        if not isinstance(stars, int) or isinstance(stars, bool) or stars < 0:
            raise ValidationError(f"{name} has an invalid current star count")
        admitted = agent["stars_at_addition"]
        if (
            not isinstance(admitted, int)
            or isinstance(admitted, bool)
            or admitted < minimum
        ):
            raise ValidationError(
                f"{name} did not meet the {minimum}-star admission threshold"
            )
        parse_date(agent["added_at"], f"{name}.added_at")

    if agents != sort_agents(agents):
        raise ValidationError(
            "agents must be sorted by exact stars descending, then by name"
        )


def format_stars(count: int) -> str:
    if count >= 100_000:
        return f"{round(count / 1000):d}k"
    if count >= 1_000:
        value = f"{count / 1000:.1f}"
        return f"{value[:-2] if value.endswith('.0') else value}k"
    return str(count)


def render_ranking(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for agent in data["agents"]:
        tags = " · ".join(f"`{item}`" for item in agent["interfaces"])
        lines.append(
            f"- [{agent['name']}](https://github.com/{agent['repo']}) - "
            f"**{format_stars(agent['stars'])} stars** · {tags} · "
            f"`{agent['license']}`. {agent['description']}"
        )
    return "\n".join(lines)


def build_readme(template: str, data: dict[str, Any]) -> str:
    if template.count(START_MARKER) != 1 or template.count(END_MARKER) != 1:
        raise ValidationError("README must contain exactly one generated ranking block")
    start = template.index(START_MARKER)
    end = template.index(END_MARKER)
    if start >= end:
        raise ValidationError("README ranking markers are out of order")

    ranking = render_ranking(data)
    generated = (
        template[: start + len(START_MARKER)]
        + "\n"
        + ranking
        + "\n"
        + template[end:]
    )
    summary = (
        f"**Last verified:** {data['last_updated']} · "
        f"**Minimum at admission:** {data['minimum_stars']:,} stars · "
        f"**Projects:** {len(data['agents'])}"
    )
    generated, replacements = SUMMARY_PATTERN.subn(summary, generated, count=1)
    if replacements != 1:
        raise ValidationError("README verification summary is missing or invalid")
    return generated.rstrip() + "\n"


def load_data(path: Path = DATA_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read {path}: {error}") from error


def github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "awesome-coding-agent-star-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github_repo(repo: str, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}", headers=github_headers(token)
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RefreshError(f"{repo}: GitHub returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RefreshError(f"{repo}: {error}") from error

    required = {"full_name", "stargazers_count", "archived", "fork"}
    if not required.issubset(payload):
        raise RefreshError(f"{repo}: GitHub returned incomplete metadata")
    return payload


def fetch_all(
    agents: list[dict[str, Any]],
    fetcher: Callable[[str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for agent in agents:
        repo = agent["repo"]
        try:
            metadata[repo] = fetcher(repo)
        except Exception as error:  # Collect every failed repository before exiting.
            errors.append(str(error))
    if errors:
        raise RefreshError("GitHub refresh failed:\n- " + "\n- ".join(errors))
    return metadata


def inspect_live_metadata(
    data: dict[str, Any], metadata: dict[str, dict[str, Any]]
) -> list[str]:
    warnings: list[str] = []
    minimum = data["minimum_stars"]
    for agent in data["agents"]:
        repo = agent["repo"]
        current = metadata[repo]
        canonical = current["full_name"]
        if canonical.casefold() != repo.casefold():
            raise RefreshError(f"{repo} now resolves to {canonical}; update the canonical record")
        if current["archived"]:
            warnings.append(f"{repo} is archived and needs maintainer review")
        if current["fork"]:
            warnings.append(f"{repo} is now marked as a fork and needs maintainer review")
        if current["stargazers_count"] < minimum:
            warnings.append(
                f"{repo} now has {current['stargazers_count']} stars; keep it pending review"
            )
    return warnings


def refresh_data(
    data: dict[str, Any],
    fetcher: Callable[[str], dict[str, Any]],
    today: str,
) -> tuple[dict[str, Any], list[str]]:
    metadata = fetch_all(data["agents"], fetcher)
    warnings = inspect_live_metadata(data, metadata)
    refreshed = copy.deepcopy(data)
    for agent in refreshed["agents"]:
        agent["stars"] = metadata[agent["repo"]]["stargazers_count"]
    refreshed["agents"] = sort_agents(refreshed["agents"])
    refreshed["last_updated"] = today
    validate_data(refreshed)
    return refreshed, warnings


def json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp:
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
            temp_name = temp.name
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def write_outputs(data: dict[str, Any], readme_template: str) -> None:
    readme = build_readme(readme_template, data)
    atomic_write(DATA_PATH, json_text(data))
    atomic_write(README_PATH, readme)


def check_repository(data: dict[str, Any], readme: str) -> None:
    validate_data(data)
    expected = build_readme(readme, data)
    if expected != readme:
        raise ValidationError(
            "README ranking is out of sync; run python scripts/update-stars.py --generate"
        )


def print_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate files without writing")
    mode.add_argument("--generate", action="store_true", help="regenerate README from data")
    mode.add_argument(
        "--verify-live",
        action="store_true",
        help="verify canonical, archive, fork, and threshold status on GitHub",
    )
    mode.add_argument("--refresh", action="store_true", help="refresh stars and README")
    args = parser.parse_args(argv)

    try:
        data = load_data()
        readme = README_PATH.read_text(encoding="utf-8")
        validate_data(data)

        if args.check:
            check_repository(data, readme)
            print(f"Validated {len(data['agents'])} agents.")
            return 0

        if args.generate:
            atomic_write(README_PATH, build_readme(readme, data))
            print(f"Generated README for {len(data['agents'])} agents.")
            return 0

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        fetcher = lambda repo: fetch_github_repo(repo, token)  # noqa: E731

        if args.verify_live:
            metadata = fetch_all(data["agents"], fetcher)
            warnings = inspect_live_metadata(data, metadata)
            print_warnings(warnings)
            print(f"Verified {len(data['agents'])} live GitHub repositories.")
            return 0

        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        refreshed, warnings = refresh_data(data, fetcher, today)
        print_warnings(warnings)
        write_outputs(refreshed, readme)
        print(f"Refreshed {len(refreshed['agents'])} agents.")
        return 0
    except (OSError, ValidationError, RefreshError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
