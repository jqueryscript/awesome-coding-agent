from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "update-stars.py"
SPEC = importlib.util.spec_from_file_location("update_stars", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {MODULE_PATH}")
update_stars = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update_stars
SPEC.loader.exec_module(update_stars)


def make_agent(name: str, repo: str, stars: int = 500) -> dict:
    return {
        "name": name,
        "repo": repo,
        "interfaces": ["CLI"],
        "license": "MIT",
        "description": f"{name} reads repositories and completes software development tasks.",
        "stars": stars,
        "stars_at_addition": max(stars, 500),
        "added_at": "2026-08-01",
    }


def make_data(*agents: dict) -> dict:
    return {
        "last_updated": "2026-08-01",
        "minimum_stars": 500,
        "agents": list(agents),
    }


def metadata(repo: str, stars: int, **overrides: object) -> dict:
    result = {
        "full_name": repo,
        "stargazers_count": stars,
        "archived": False,
        "fork": False,
    }
    result.update(overrides)
    return result


class StarFormattingTests(unittest.TestCase):
    def test_formats_exact_and_short_counts(self) -> None:
        self.assertEqual(update_stars.format_stars(742), "742")
        self.assertEqual(update_stars.format_stars(1_000), "1k")
        self.assertEqual(update_stars.format_stars(12_582), "12.6k")
        self.assertEqual(update_stars.format_stars(191_773), "192k")


class RefreshTests(unittest.TestCase):
    def test_refresh_restores_star_order(self) -> None:
        original = make_data(
            make_agent("Alpha", "example/alpha", 900),
            make_agent("Beta", "example/beta", 800),
        )
        values = {
            "example/alpha": metadata("example/alpha", 700),
            "example/beta": metadata("example/beta", 1_200),
        }
        refreshed, warnings = update_stars.refresh_data(
            original, values.__getitem__, "2026-08-02"
        )
        self.assertEqual([item["name"] for item in refreshed["agents"]], ["Beta", "Alpha"])
        self.assertEqual(refreshed["last_updated"], "2026-08-02")
        self.assertEqual(warnings, [])

    def test_equal_stars_use_case_insensitive_name_order(self) -> None:
        original = make_data(
            make_agent("Alpha", "example/alpha", 900),
            make_agent("beta", "example/beta", 800),
        )
        values = {
            "example/alpha": metadata("example/alpha", 1_000),
            "example/beta": metadata("example/beta", 1_000),
        }
        refreshed, _ = update_stars.refresh_data(
            original, values.__getitem__, "2026-08-02"
        )
        self.assertEqual([item["name"] for item in refreshed["agents"]], ["Alpha", "beta"])

    def test_fetch_failure_does_not_mutate_data(self) -> None:
        original = make_data(
            make_agent("Alpha", "example/alpha", 900),
            make_agent("Beta", "example/beta", 800),
        )
        before = copy.deepcopy(original)

        def failing_fetcher(repo: str) -> dict:
            if repo.endswith("beta"):
                raise update_stars.RefreshError("simulated API failure")
            return metadata(repo, 1_000)

        with self.assertRaises(update_stars.RefreshError):
            update_stars.refresh_data(original, failing_fetcher, "2026-08-02")
        self.assertEqual(original, before)

    def test_below_threshold_is_kept_and_flagged(self) -> None:
        original = make_data(make_agent("Alpha", "example/alpha", 900))
        values = {"example/alpha": metadata("example/alpha", 499)}
        refreshed, warnings = update_stars.refresh_data(
            original, values.__getitem__, "2026-08-02"
        )
        self.assertEqual(refreshed["agents"][0]["stars"], 499)
        self.assertIn("pending review", warnings[0])


class ValidationTests(unittest.TestCase):
    def test_rejects_duplicate_repository(self) -> None:
        data = make_data(
            make_agent("Alpha", "example/project", 900),
            make_agent("Beta", "EXAMPLE/project", 800),
        )
        with self.assertRaisesRegex(update_stars.ValidationError, "duplicate repository"):
            update_stars.validate_data(data)

    def test_rejects_missing_field(self) -> None:
        agent = make_agent("Alpha", "example/alpha")
        del agent["license"]
        with self.assertRaisesRegex(update_stars.ValidationError, "missing"):
            update_stars.validate_data(make_data(agent))

    def test_rejects_invalid_interface(self) -> None:
        agent = make_agent("Alpha", "example/alpha")
        agent["interfaces"] = ["Mobile"]
        with self.assertRaisesRegex(update_stars.ValidationError, "interfaces"):
            update_stars.validate_data(make_data(agent))

    def test_rejects_project_admitted_below_threshold(self) -> None:
        agent = make_agent("Alpha", "example/alpha")
        agent["stars_at_addition"] = 499
        with self.assertRaisesRegex(update_stars.ValidationError, "admission threshold"):
            update_stars.validate_data(make_data(agent))

    def test_rejects_unsorted_data(self) -> None:
        data = make_data(
            make_agent("Alpha", "example/alpha", 500),
            make_agent("Beta", "example/beta", 600),
        )
        with self.assertRaisesRegex(update_stars.ValidationError, "sorted"):
            update_stars.validate_data(data)


class ReadmeTests(unittest.TestCase):
    def test_generation_is_idempotent_and_updates_summary(self) -> None:
        data = make_data(make_agent("Alpha", "example/alpha", 900))
        template = (
            "# Title\n\n"
            "**Last verified:** 2026-01-01 · **Minimum at admission:** 100 stars · "
            "**Projects:** 0\n\n"
            f"{update_stars.START_MARKER}\nold\n{update_stars.END_MARKER}\n"
        )
        first = update_stars.build_readme(template, data)
        second = update_stars.build_readme(first, data)
        self.assertEqual(first, second)
        self.assertIn("**Projects:** 1", first)
        self.assertIn("https://github.com/example/alpha", first)


if __name__ == "__main__":
    unittest.main()
