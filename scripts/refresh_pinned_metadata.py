#!/usr/bin/env python3
"""Refresh selected derived metadata without resolving or changing source pins."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import sys
from typing import Any

from build_index import atomic_write_text, build_entry, github_request, reject_json_constant
from validate_index import validate_policy


def refresh_entry(entry: dict[str, Any], payload: bytes) -> dict[str, Any]:
    metadata = entry["meta"]
    repository = entry["repository"]
    repo = {
        "full_name": repository.removeprefix("https://github.com/"),
        "html_url": repository,
        "default_branch": metadata["default_branch"],
        "owner": {"login": "attune-packs"},
        "description": entry["description"],
        "stargazers_count": metadata["stars"],
        "id": metadata["repository_id"],
        # Retain the published fallback, never substitute current-branch API data.
        "license": {"spdx_id": entry["license"]},
    }
    generated = build_entry(repo, metadata["commit"], payload)
    changed = {
        key for key in entry.keys() | generated.keys()
        if entry.get(key) != generated.get(key)
    }
    unexpected = changed - {"runtime_deps", "license"}
    if unexpected:
        raise ValueError(
            f"{entry['ref']}: pinned regeneration changed protected fields: "
            f"{', '.join(sorted(unexpected))}"
        )
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Example: %(prog)s --baseline published-index.json --pack azure --output index.json",
    )
    parser.add_argument("--baseline", required=True, type=pathlib.Path, help="Saved published index")
    parser.add_argument("--pack", required=True, action="append", help="Pack ref to refresh; repeatable")
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path("index.json"))
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"), parse_constant=reject_json_constant)
    errors = validate_policy(baseline)
    if errors:
        raise ValueError("Invalid baseline: " + "; ".join(errors))
    refs = {pack["ref"] for pack in baseline["packs"]}
    unknown = set(args.pack) - refs
    if unknown:
        parser.error(f"Unknown pack refs in baseline: {', '.join(sorted(unknown))}")

    result = copy.deepcopy(baseline)
    for position, entry in enumerate(result["packs"]):
        if entry["ref"] not in args.pack:
            continue
        source = next(source for source in entry["install_sources"] if source["type"] == "archive")
        result["packs"][position] = refresh_entry(entry, github_request(source["url"]))
        print(f"Verified {entry['ref']}@{entry['meta']['commit']}: both source checksums preserved", file=sys.stderr)

    if result != baseline:
        result["last_updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"), parse_constant=reject_json_constant)
        if {**previous, "last_updated": result["last_updated"]} == result:
            result["last_updated"] = previous["last_updated"]
    changed = atomic_write_text(args.output, json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False) + "\n")
    print(f"{'Wrote' if changed else 'Unchanged'} {len(result['packs'])} packs at {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
