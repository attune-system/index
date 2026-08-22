#!/usr/bin/env python3
"""Validate an Attune pack index and standard-index publishing policy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jsonschema


COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def source_url_has_forbidden_parts(raw_url: str) -> bool:
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return True

    if parsed.username or parsed.password is not None:
        return True

    without_query_or_fragment = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return raw_url != without_query_or_fragment


def validate_policy(index: dict[str, Any], standard: bool = True) -> list[str]:
    errors: list[str] = []
    registry_url = index.get("registry_url")
    if isinstance(registry_url, str) and source_url_has_forbidden_parts(registry_url):
        errors.append(
            "registry_url must not contain credentials, query strings, or fragments"
        )
    refs = [pack["ref"] for pack in index["packs"]]
    if refs != sorted(refs):
        errors.append("packs must be sorted by ref")
    if len(refs) != len(set(refs)):
        errors.append("pack refs must be unique")

    try:
        dt.datetime.fromisoformat(index["last_updated"].replace("Z", "+00:00"))
    except ValueError:
        errors.append("last_updated must be an ISO 8601 timestamp")

    for pack in index["packs"]:
        component_names: set[tuple[str, str]] = set()
        for component_type, components in pack["contents"].items():
            for component in components:
                key = (component_type, component["name"])
                if key in component_names:
                    errors.append(f"{pack['ref']}: duplicate {component_type} component {component['name']}")
                component_names.add(key)

        for source in pack["install_sources"]:
            if source_url_has_forbidden_parts(source["url"]):
                errors.append(
                    f"{pack['ref']}: install source URLs must not contain credentials, query strings, or fragments"
                )

        git_sources = [source for source in pack["install_sources"] if source["type"] == "git"]
        if standard:
            if not pack.get("repository", "").startswith("https://github.com/attune-packs/"):
                errors.append(f"{pack['ref']}: standard entries must come from attune-packs")
            if len(git_sources) != 1 or not COMMIT_SHA.fullmatch(git_sources[0].get("ref", "")):
                errors.append(f"{pack['ref']}: standard Git source must use one immutable commit SHA")
        elif any(not COMMIT_SHA.fullmatch(source.get("ref", "")) for source in git_sources):
            errors.append(f"{pack['ref']}: Git sources must use immutable 40-character commit SHAs")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=pathlib.Path, default=pathlib.Path("index.json"))
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        default=pathlib.Path("schema/index.schema.json"),
    )
    parser.add_argument("--custom", action="store_true", help="Skip attune-packs source policy")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = json.loads(
        args.index.read_text(encoding="utf-8"), parse_constant=reject_json_constant
    )
    schema = json.loads(
        args.schema.read_text(encoding="utf-8"), parse_constant=reject_json_constant
    )

    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    schema_errors = sorted(validator.iter_errors(index), key=lambda error: list(error.path))
    errors = [f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in schema_errors]
    if not errors:
        errors.extend(validate_policy(index, standard=not args.custom))

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(index['packs'])} pack entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
