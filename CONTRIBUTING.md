# Contribution Guidelines

Thank you for helping maintain Awesome Coding Agents. The list is curated, so meeting the star threshold does not guarantee inclusion.

## Before You Submit

A new project must satisfy every requirement below:

- The link points to the project's official public GitHub repository.
- The repository has at least 500 GitHub stars when the pull request is opened.
- The product accepts development tasks, reads a codebase, and can edit files, run commands, test, or debug.
- The repository is active, is not archived, and is not a mirror or a minimally changed fork of a listed project.
- The project is an independent coding agent, not a completion-only extension, prompt collection, skills repository, SDK, general agent framework, session manager, or orchestration tool.
- The description is factual, specific, and supported by the project's documentation.

Search [`data/agents.json`](data/agents.json) before proposing a project. Duplicate products and duplicate repositories will not be accepted.

## Add a Project

Edit `data/agents.json`. Do not edit the generated ranking inside `README.md` by hand.

Use this record shape:

```json
{
  "name": "Project Name",
  "repo": "owner/repository",
  "interfaces": ["CLI"],
  "license": "MIT",
  "description": "A concrete sentence explaining what the coding agent can do.",
  "stars": 1234,
  "stars_at_addition": 1234,
  "added_at": "2026-08-01"
}
```

Allowed interface labels are `CLI`, `IDE`, `Web`, `Desktop`, and `Autonomous`. Use the repository's SPDX identifier when GitHub detects one. Use `Source Available` when source is public without a recognized open-source license, or `Closed Source` when the official repository distributes or tracks a proprietary product without publishing its source.

Record the exact current GitHub star count in both star fields. The maintenance script will refresh the count and place the project in the correct position.

## Update or Remove a Project

Submit corrections when a project moves, changes its license, is archived, or no longer meets the list's definition. Include a short explanation and link to the project's own documentation when the reason is not evident from the repository.

A project that later falls below 500 stars is flagged for maintainer review. The scheduled updater does not remove it automatically.

## Validate Your Change

Run these commands before opening a pull request:

```sh
python scripts/update-stars.py --generate
python -m unittest discover -s tests -v
python scripts/update-stars.py --check
npx awesome-lint
```

The pull request checks also verify live repository status and Markdown links. Keep each pull request focused on one project or one clearly related correction.

## Writing Style

- Write in standard American English.
- Start descriptions with a capital letter and end them with a period.
- State what the agent does in one sentence.
- Avoid slogans, unsupported comparisons, feature dumps, and promotional claims.
- Do not copy a project's marketing text verbatim.
