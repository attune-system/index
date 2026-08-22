#!/usr/bin/env python3
"""Build an Attune pack index from public GitHub repositories."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import os
import pathlib
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from typing import Any

import yaml


COMPONENT_DIRECTORIES = ("actions", "sensors", "triggers", "rules", "workflows")
GITHUB_API = "https://api.github.com"


def reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def github_request(url: str, token: str | None = None) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "attune-pack-index-builder",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed ({error.code}) for {url}: {detail}") from error


def github_json(path: str, token: str | None = None) -> Any:
    return json.loads(github_request(f"{GITHUB_API}{path}", token))


def list_repositories(org: str, token: str | None) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = github_json(
            f"/orgs/{org}/repos?type=public&per_page=100&page={page}&sort=full_name",
            token,
        )
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [repo for repo in repositories if not repo["archived"] and not repo["fork"]]


def get_repository(full_name: str, token: str | None) -> dict[str, Any]:
    return github_json(f"/repos/{full_name}", token)


def get_commit_sha(full_name: str, branch: str, token: str | None) -> str:
    commit = github_json(f"/repos/{full_name}/commits/{branch}", token)
    return commit["sha"]


def unpack_github_archive(payload: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        roots = {member.name.split("/", 1)[0] for member in members if member.name}
        if len(roots) != 1:
            raise ValueError("GitHub archive must contain exactly one root directory")
        root = roots.pop()

        for member in members:
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Pack archive contains a non-regular file: {member.name}")
            prefix = f"{root}/"
            if not member.name.startswith(prefix):
                raise ValueError(f"Archive member is outside its root: {member.name}")
            relative = member.name[len(prefix) :]
            path = pathlib.PurePosixPath(relative)
            if not relative or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member path: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"Unable to read archive member: {member.name}")
            files[relative] = extracted.read()
    return files


def attune_directory_checksum(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        path_bytes = path.encode("utf-8")
        content = files[path]
        digest.update(b"attune-pack-file-v1")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def load_yaml(files: dict[str, bytes], path: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(files[path].decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to parse {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return value


def scalar_string(value: Any, field: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"pack.yaml {field} values must be strings or finite numbers")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"pack.yaml {field} values must be strings or finite numbers")
    return json.dumps(value, allow_nan=False)


def strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"pack.yaml {field} must be an array")
    return sorted({scalar_string(item, field) for item in value})


def required_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"pack.yaml {field} must be a string")
    return value


def preferred_string(
    manifest: dict[str, Any],
    field: str,
    metadata: dict[str, Any],
    metadata_field: str,
) -> str | None:
    if field in manifest:
        return required_string(manifest[field], field)
    if metadata_field in metadata:
        return required_string(metadata[metadata_field], f"meta.{metadata_field}")
    return None


def manifest_keywords(manifest: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    for source, field in (
        (manifest, "tags"),
        (manifest, "keywords"),
        (metadata, "keywords"),
    ):
        if field in source:
            prefix = "meta." if source is metadata else ""
            return strings(source[field], f"{prefix}{field}")
    return []


def normalize_meta(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("pack.yaml meta must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("pack.yaml meta keys must be strings")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"pack.yaml meta must be JSON-compatible: {error}") from error
    tested_versions = value.get("tested_attune_versions")
    if tested_versions is not None:
        if not isinstance(tested_versions, list) or any(
            not isinstance(version, str) for version in tested_versions
        ):
            raise ValueError("pack.yaml meta.tested_attune_versions must be an array of strings")
        if len(tested_versions) != len(set(tested_versions)):
            raise ValueError("pack.yaml meta.tested_attune_versions values must be unique")
    return dict(value)


def optional_nonempty_string(metadata: dict[str, Any], fields: tuple[str, ...], context: str) -> str | None:
    for field in fields:
        if field not in metadata:
            continue
        value = metadata[field]
        if not isinstance(value, str):
            raise ValueError(f"{context} {field} must be a string")
        if value:
            return value
    return None


def component_summary(metadata: dict[str, Any], pack_ref: str, fallback: str, context: str) -> dict[str, str]:
    name = optional_nonempty_string(metadata, ("ref", "name"), context) or fallback
    prefix = f"{pack_ref}."
    if name.startswith(prefix):
        name = name[len(prefix) :]
    description = optional_nonempty_string(metadata, ("description", "label"), context) or ""
    return {"name": name, "description": description}


def inline_component_summaries(
    manifest: dict[str, Any], component_type: str
) -> list[dict[str, str]]:
    if component_type not in manifest:
        return []
    components = manifest[component_type]
    if not isinstance(components, dict):
        raise ValueError(f"pack.yaml {component_type} must be an object")

    summaries: list[dict[str, str]] = []
    for name, metadata in components.items():
        if not isinstance(name, str):
            raise ValueError(f"pack.yaml {component_type} component names must be strings")
        if not isinstance(metadata, dict):
            raise ValueError(f"pack.yaml {component_type}.{name} must be an object")
        optional_nonempty_string(
            metadata, ("workflow_file",), f"{component_type}.{name}"
        )
        description = optional_nonempty_string(
            metadata, ("description", "label"), f"{component_type}.{name}"
        ) or ""
        summaries.append({"name": name, "description": description})
    return sorted(summaries, key=lambda item: item["name"])


def inventory_components(
    files: dict[str, bytes], pack_ref: str, manifest: dict[str, Any]
) -> dict[str, list[dict[str, str]]]:
    contents: dict[str, list[dict[str, str]]] = {name: [] for name in COMPONENT_DIRECTORIES}
    for directory in COMPONENT_DIRECTORIES:
        prefix = f"{directory}/"
        component_paths = [
            path
            for path in sorted(files)
            if path.startswith(prefix)
            and "/" not in path[len(prefix) :]
            and path.endswith((".yaml", ".yml"))
        ]
        if not component_paths:
            contents[directory].extend(inline_component_summaries(manifest, directory))
            continue
        for path in component_paths:
            relative = path[len(prefix) :]
            metadata = load_yaml(files, path)
            target = directory
            if directory == "actions":
                workflow_file = optional_nonempty_string(
                    metadata, ("workflow_file",), f"component {path}"
                )
                if workflow_file:
                    target = "workflows"
            fallback = pathlib.PurePosixPath(relative).stem
            contents[target].append(
                component_summary(metadata, pack_ref, fallback, f"component {path}")
            )

    for values in contents.values():
        values.sort(key=lambda item: item["name"])
    return contents


def normalize_dependencies(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        return {"packs": strings(value, "dependencies")}
    if not isinstance(value, dict):
        raise ValueError("pack.yaml dependencies must be an array or object")

    result: dict[str, Any] = {}
    for field in ("attune_version", "python_version", "nodejs_version"):
        if field in value:
            result[field] = scalar_string(value[field], f"dependencies.{field}")
    result["packs"] = strings(value.get("packs", []), "dependencies.packs")
    return result


def build_entry(repo: dict[str, Any], sha: str, payload: bytes) -> dict[str, Any]:
    files = unpack_github_archive(payload)
    if "pack.yaml" not in files:
        raise ValueError(f"{repo['full_name']} does not contain pack.yaml at its root")
    manifest = load_yaml(files, "pack.yaml")
    metadata = normalize_meta(manifest["meta"]) if "meta" in manifest else {}

    if "ref" not in manifest or "version" not in manifest:
        raise ValueError(f"{repo['full_name']} pack.yaml must declare ref and version")
    pack_ref = required_string(manifest["ref"], "ref")
    version = required_string(manifest["version"], "version")
    if not pack_ref or not version:
        raise ValueError(f"{repo['full_name']} pack.yaml must declare nonempty ref and version")

    license_id = preferred_string(manifest, "license", metadata, "license")
    if license_id is None:
        license_data = repo.get("license") or {}
        license_id = license_data.get("spdx_id") or "NOASSERTION"

    keywords = manifest_keywords(manifest, metadata)
    homepage = preferred_string(manifest, "homepage", metadata, "documentation_url")
    source_url = repo["html_url"]
    archive_url = f"https://codeload.github.com/{repo['full_name']}/tar.gz/{sha}"
    directory_checksum = attune_directory_checksum(files)

    entry_metadata = dict(metadata)
    entry_metadata.setdefault("category", "uncategorized")
    entry_metadata.update(
        {
            "default_branch": repo["default_branch"],
            "commit": sha,
            "stars": int(repo.get("stargazers_count") or 0),
        }
    )

    entry: dict[str, Any] = {
        "ref": pack_ref,
        "label": required_string(
            manifest["label"] if "label" in manifest else manifest.get("name", pack_ref),
            "label" if "label" in manifest else "name",
        ),
        "description": required_string(manifest["description"], "description")
        if "description" in manifest
        else str(repo.get("description") or ""),
        "version": version,
        "author": required_string(manifest["author"], "author")
        if "author" in manifest
        else str(repo["owner"]["login"]),
        "license": str(license_id),
        "keywords": keywords,
        "runtime_deps": strings(manifest.get("runtime_deps", []), "runtime_deps"),
        "install_sources": [
            {
                "type": "git",
                "url": f"{source_url}.git",
                "ref": sha,
                "checksum": f"sha256:{directory_checksum}",
            },
            {
                "type": "archive",
                "url": archive_url,
                "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            },
        ],
        "contents": inventory_components(files, pack_ref, manifest),
        "meta": entry_metadata,
        "repository": source_url,
    }

    if "email" in manifest:
        entry["email"] = required_string(manifest["email"], "email")
    if homepage is not None:
        entry["homepage"] = str(homepage)
    use_case = preferred_string(manifest, "use_case", metadata, "use_case")
    if use_case is not None:
        entry["use_case"] = str(use_case)
    dependencies = (
        normalize_dependencies(manifest["dependencies"])
        if "dependencies" in manifest
        else None
    )
    if dependencies is not None:
        entry["dependencies"] = dependencies
    return entry


def read_existing(path: pathlib.Path, registry_name: str, registry_url: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_json_constant
        )
    return {
        "registry_name": registry_name,
        "registry_url": registry_url,
        "version": "1.0",
        "last_updated": "1970-01-01T00:00:00Z",
        "packs": [],
    }


def atomic_write_text(path: pathlib.Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = pathlib.Path(temporary_name)
    try:
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    return True


def merge_entries(
    existing: dict[str, dict[str, Any]],
    generated: dict[str, dict[str, Any]],
    target_repositories: set[str],
    partial: bool,
) -> dict[str, dict[str, Any]]:
    if not partial:
        return generated

    entries = {
        pack_ref: entry
        for pack_ref, entry in existing.items()
        if entry.get("repository") not in target_repositories
    }
    for pack_ref, entry in generated.items():
        conflicting = entries.get(pack_ref)
        if conflicting is not None:
            raise ValueError(
                f"Pack ref {pack_ref!r} is already owned by {conflicting.get('repository', 'an unknown repository')}"
            )
        entries[pack_ref] = entry
    return entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default="attune-packs", help="GitHub organization to scan")
    parser.add_argument(
        "--repository",
        action="append",
        default=[],
        help="Update only this owner/repository; may be repeated",
    )
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path("index.json"))
    parser.add_argument("--registry-name", default="Attune Standard Pack Index")
    parser.add_argument("--registry-url", default="https://github.com/attune-system/index")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    existing = read_existing(args.output, args.registry_name, args.registry_url)
    existing_entries = {entry["ref"]: entry for entry in existing.get("packs", [])}

    partial = bool(args.repository)
    if partial:
        repositories = [get_repository(name, token) for name in args.repository]
    else:
        repositories = list_repositories(args.org, token)

    generated: dict[str, dict[str, Any]] = {}
    for repo in sorted(repositories, key=lambda item: item["full_name"]):
        sha = get_commit_sha(repo["full_name"], repo["default_branch"], token)
        archive_url = f"https://codeload.github.com/{repo['full_name']}/tar.gz/{sha}"
        print(f"Indexing {repo['full_name']}@{sha[:12]}", file=sys.stderr)
        payload = github_request(archive_url, token)
        entry = build_entry(repo, sha, payload)
        if entry["ref"] in generated:
            raise ValueError(f"Duplicate pack ref generated: {entry['ref']}")
        generated[entry["ref"]] = entry

    target_repositories = {repo["html_url"] for repo in repositories}
    entries = merge_entries(existing_entries, generated, target_repositories, partial)
    packs = [entries[pack_ref] for pack_ref in sorted(entries)]
    changed = (
        packs != existing.get("packs", [])
        or args.registry_name != existing.get("registry_name")
        or args.registry_url != existing.get("registry_url")
        or existing.get("version") != "1.0"
    )
    timestamp = existing.get("last_updated", "1970-01-01T00:00:00Z")
    if changed:
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    index = {
        "registry_name": args.registry_name,
        "registry_url": args.registry_url,
        "version": "1.0",
        "last_updated": timestamp,
        "packs": packs,
    }
    content = json.dumps(index, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    changed_on_disk = atomic_write_text(args.output, content)
    action = "Wrote" if changed_on_disk else "Unchanged"
    print(f"{action} {len(packs)} packs at {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
