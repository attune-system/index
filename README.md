# Attune Standard Pack Index

This repository publishes the standard index for public packs maintained in
the [`attune-packs`](https://github.com/attune-packs) GitHub organization.

The consumable index is [`index.json`](index.json):

```text
https://raw.githubusercontent.com/attune-system/index/main/index.json
```

Add it to Attune with:

```sh
attune pack index add \
  https://raw.githubusercontent.com/attune-system/index/main/index.json \
  --name "Attune Standard Pack Index"
```

The Attune deployment must allow `raw.githubusercontent.com`, `github.com`,
and `codeload.github.com` in its pack registry public-host policy.

## Publishing Model

Each index entry represents the `version` declared by a pack's root
`pack.yaml` at an immutable commit from the repository's default branch. The
entry provides two verified sources:

- A Git URL pinned to the 40-character commit SHA, with an Attune directory
  checksum.
- A GitHub source archive pinned to the same commit, with a SHA-256 checksum
  of the downloaded archive.

The index is rebuilt on a schedule. Pack repositories can request an immediate
refresh through the reusable workflow in this repository.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `index.json` | Generated standard index consumed by Attune |
| `schema/index.schema.json` | Machine-readable index format contract |
| `scripts/build_index.py` | Deterministic GitHub organization index builder |
| `scripts/validate_index.py` | Schema and standard-index policy validation |
| `.github/workflows/sync.yml` | Scheduled and event-driven index refresh |
| `.github/workflows/publish-pack.yml` | Reusable workflow called by pack repositories |
| `templates/publish-pack-index.yml` | Thin caller workflow for pack repositories |
| `docs/` | Automation contract, architecture, inventory, custom-index, publishing, and operations guides |

## Local Development

Python 3.11 or newer is required.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py
python scripts/validate_index.py
python -m unittest discover -s tests -v
```

See [Building a Custom Index](docs/custom-index.md) to use the tooling for
another GitHub organization. See [Pack Publishing](docs/pack-publishing.md)
for the standard-index onboarding flow.

The initial organization inventory and known metadata gaps are recorded in
[Current State](docs/current-state.md).

Maintainers of the index and participating pack repositories should also read
the [Automation Contract](docs/automation-contract.md), which defines triggers,
ownership, guarantees, recovery behavior, and credential expectations.
