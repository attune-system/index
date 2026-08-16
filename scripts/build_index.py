#!/usr/bin/env python3
"""Build an Attune pack index from public GitHub repositories."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import sys
import tarfile
import urllib.error
import urllib.request
from typing import Any

import yaml


COMPONENT_DIRECTORIES = ("actions", "sensors", "triggers", "rules", "workflows")
GITHUB_API = "https://api.github.com"


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


def strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if isinstance(item, (str, int, float))})


def component_summary(metadata: dict[str, Any], pack_ref: str, fallback: str) -> dict[str, str]:
    component_ref = metadata.get("ref") or metadata.get("name") or fallback
    name = str(component_ref)
    prefix = f"{pack_ref}."
    if name.startswith(prefix):
        name = name[len(prefix) :]
    description = metadata.get("description") or metadata.get("label") or ""
    return {"name": name, "description": str(description)}


def inventory_components(files: dict[str, bytes], pack_ref: str) -> dict[str, list[dict[str, str]]]:
    contents: dict[str, list[dict[str, str]]] = {name: [] for name in COMPONENT_DIRECTORIES}
    for directory in COMPONENT_DIRECTORIES:
        prefix = f"{directory}/"
        for path in sorted(files):
            relative = path[len(prefix) :] if path.startswith(prefix) else ""
            if not relative or "/" in relative or not relative.endswith((".yaml", ".yml")):
                continue
            metadata = load_yaml(files, path)
            target = directory
            if directory == "actions" and metadata.get("workflow_file"):
                target = "workflows"
            fallback = pathlib.PurePosixPath(relative).stem
            contents[target].append(component_summary(metadata, pack_ref, fallback))

    for values in contents.values():
        values.sort(key=lambda item: item["name"])
    return contents


def normalize_dependencies(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        return {"packs": strings(value)}
    if not isinstance(value, dict):
        return None

    result: dict[str, Any] = {}
    for field in ("attune_version", "python_version", "nodejs_version"):
        if value.get(field) is not None:
            result[field] = str(value[field])
    result["packs"] = strings(value.get("packs", []))
    return result


def build_entry(repo: dict[str, Any], sha: str, payload: bytes) -> dict[str, Any]:
    files = unpack_github_archive(payload)
    if "pack.yaml" not in files:
        raise ValueError(f"{repo['full_name']} does not contain pack.yaml at its root")
    manifest = load_yaml(files, "pack.yaml")
    metadata = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}

    pack_ref = str(manifest.get("ref") or "")
    version = str(manifest.get("version") or "")
    if not pack_ref or not version:
        raise ValueError(f"{repo['full_name']} pack.yaml must declare ref and version")

    license_id = manifest.get("license") or metadata.get("license")
    if not license_id:
        license_data = repo.get("license") or {}
        license_id = license_data.get("spdx_id") or "NOASSERTION"

    keywords = manifest.get("keywords") or metadata.get("keywords") or manifest.get("tags") or []
    homepage = manifest.get("homepage") or metadata.get("documentation_url")
    source_url = repo["html_url"]
    archive_url = f"https://codeload.github.com/{repo['full_name']}/tar.gz/{sha}"
    directory_checksum = attune_directory_checksum(files)

    entry: dict[str, Any] = {
        "ref": pack_ref,
        "label": str(manifest.get("label") or manifest.get("name") or pack_ref),
        "description": str(manifest.get("description") or repo.get("description") or ""),
        "version": version,
        "author": str(manifest.get("author") or repo["owner"]["login"]),
        "license": str(license_id),
        "keywords": strings(keywords),
        "runtime_deps": strings(manifest.get("runtime_deps", [])),
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
        "contents": inventory_components(files, pack_ref),
        "meta": {
            "category": str(metadata.get("category") or "uncategorized"),
            "default_branch": repo["default_branch"],
            "commit": sha,
            "stars": int(repo.get("stargazers_count") or 0),
        },
        "repository": source_url,
    }

    if manifest.get("email"):
        entry["email"] = str(manifest["email"])
    if homepage:
        entry["homepage"] = str(homepage)
    if metadata.get("use_case") or manifest.get("use_case"):
        entry["use_case"] = str(manifest.get("use_case") or metadata["use_case"])
    dependencies = normalize_dependencies(manifest.get("dependencies"))
    if dependencies is not None:
        entry["dependencies"] = dependencies
    return entry


def read_existing(path: pathlib.Path, registry_name: str, registry_url: str) -> dict[str, Any]:
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    return {
        "registry_name": registry_name,
        "registry_url": registry_url,
        "version": "1.0",
        "last_updated": "1970-01-01T00:00:00Z",
        "packs": [],
    }


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
    args.output.write_text(json.dumps(index, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(packs)} packs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
