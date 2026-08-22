from __future__ import annotations

import hashlib
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import jsonschema


sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))

from build_index import (
    atomic_write_text,
    attune_directory_checksum,
    build_entry,
    manifest_keywords,
    merge_entries,
    normalize_dependencies,
    normalize_meta,
    unpack_github_archive,
)
from validate_index import reject_json_constant, validate_policy


def archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(f"owner-repo-sha/{path}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return output.getvalue()


class RegistryTests(unittest.TestCase):
    def test_attune_checksum_frames_sorted_paths_and_contents(self) -> None:
        files = {"z.txt": b"last", "a.txt": b"first"}
        expected = hashlib.sha256()
        for path in ("a.txt", "z.txt"):
            path_bytes = path.encode()
            expected.update(b"attune-pack-file-v1")
            expected.update(len(path_bytes).to_bytes(8, "big"))
            expected.update(path_bytes)
            expected.update(len(files[path]).to_bytes(8, "big"))
            expected.update(files[path])
        self.assertEqual(attune_directory_checksum(files), expected.hexdigest())

    def test_attune_checksum_uses_canonical_nested_path_test_vector(self) -> None:
        self.assertEqual(
            attune_directory_checksum({"nested/file.txt": b"fixture\n"}),
            "e9837162383488cb9b187ea585ce8963634d7d04f75abeb0c43d5456de0d6b13",
        )

    def test_archive_rejects_symlinks(self) -> None:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            link = tarfile.TarInfo("owner-repo-sha/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "pack.yaml"
            tar.addfile(link)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            unpack_github_archive(output.getvalue())

    def test_build_entry_normalizes_manifest_and_components(self) -> None:
        payload = archive(
            {
                "pack.yaml": b"""
ref: demo
label: Demo Pack
name: Legacy Demo Name
description: A useful pack
version: 1.2.3
author: Attune
runtime_deps: [python, python]
tags: [example, demo, example]
keywords: [legacy-keyword]
dependencies: [core]
meta:
  category: examples
  license: Apache-2.0
  keywords: [meta-keyword]
  documentation_url: https://docs.example.com/demo
  repository_url: https://github.com/attune-packs/demo
  use_case: Demonstrate metadata normalization
  tested_attune_versions: [0.1.0]
  support_tier: community
""",
                "actions/hello.yaml": b"ref: demo.hello\ndescription: Say hello\n",
                "actions/deploy.yaml": b"ref: demo.deploy\ndescription: Deploy\nworkflow_file: workflows/deploy.workflow.yaml\n",
                "actions/workflows/deploy.workflow.yaml": b"tasks: []\n",
            }
        )
        repo = {
            "full_name": "attune-packs/demo",
            "html_url": "https://github.com/attune-packs/demo",
            "description": "Repository description",
            "default_branch": "main",
            "stargazers_count": 2,
            "license": None,
            "owner": {"login": "attune-packs"},
        }
        entry = build_entry(repo, "a" * 40, payload)
        self.assertEqual(entry["label"], "Demo Pack")
        self.assertEqual(entry["license"], "Apache-2.0")
        self.assertEqual(entry["keywords"], ["demo", "example"])
        self.assertEqual(entry["runtime_deps"], ["python"])
        self.assertEqual(entry["homepage"], "https://docs.example.com/demo")
        self.assertEqual(entry["use_case"], "Demonstrate metadata normalization")
        self.assertEqual(entry["dependencies"], {"packs": ["core"]})
        self.assertEqual(entry["meta"]["tested_attune_versions"], ["0.1.0"])
        self.assertEqual(entry["meta"]["support_tier"], "community")
        self.assertEqual(entry["meta"]["keywords"], ["meta-keyword"])
        self.assertEqual(entry["meta"]["default_branch"], "main")
        self.assertEqual(entry["meta"]["commit"], "a" * 40)
        self.assertEqual(entry["meta"]["stars"], 2)
        self.assertEqual(entry["contents"]["actions"][0]["name"], "hello")
        self.assertEqual(entry["contents"]["workflows"][0]["name"], "deploy")
        self.assertEqual(entry["install_sources"][0]["ref"], "a" * 40)

    def test_dependency_object_normalization_matches_index_contract(self) -> None:
        self.assertEqual(
            normalize_dependencies(
                {
                    "attune_version": ">=0.1.0",
                    "python_version": ">=3.11",
                    "nodejs_version": ">=20",
                    "packs": ["core", "core"],
                }
            ),
            {
                "attune_version": ">=0.1.0",
                "python_version": ">=3.11",
                "nodejs_version": ">=20",
                "packs": ["core"],
            },
        )
        self.assertEqual(
            normalize_dependencies(
                {"python_version": 3.0, "packs": [1, 1.0]}
            ),
            {"python_version": "3.0", "packs": ["1", "1.0"]},
        )

    def test_build_entry_inventories_inline_only_components(self) -> None:
        payload = archive(
            {
                "pack.yaml": b"""
ref: inline-only
version: 1.0.0
actions:
  run:
    description: Run inline
sensors:
  watch:
    label: Watch inline
triggers:
  changed:
    description: Changed inline
"""
            }
        )
        repo = {
            "full_name": "attune-packs/inline-only",
            "html_url": "https://github.com/attune-packs/inline-only",
            "description": None,
            "default_branch": "main",
            "stargazers_count": 0,
            "license": None,
            "owner": {"login": "attune-packs"},
        }

        entry = build_entry(repo, "a" * 40, payload)
        self.assertEqual(
            entry["contents"]["actions"],
            [{"name": "run", "description": "Run inline"}],
        )
        self.assertEqual(
            entry["contents"]["sensors"],
            [{"name": "watch", "description": "Watch inline"}],
        )
        self.assertEqual(entry["contents"]["triggers"][0]["name"], "changed")

    def test_build_entry_rejects_non_string_component_metadata(self) -> None:
        repo = {
            "full_name": "attune-packs/strict-components",
            "html_url": "https://github.com/attune-packs/strict-components",
            "description": None,
            "default_branch": "main",
            "stargazers_count": 0,
            "license": None,
            "owner": {"login": "attune-packs"},
        }
        payloads = [
            archive(
                {
                    "pack.yaml": b"""
ref: strict-components
version: 1.0.0
actions:
  invalid:
    description: 123
"""
                }
            ),
            archive(
                {
                    "pack.yaml": b"ref: strict-components\nversion: 1.0.0\n",
                    "actions/invalid.yaml": b"ref: 123\ndescription: Invalid\n",
                }
            ),
        ]

        for payload in payloads:
            with self.subTest(payload=payload[:8]):
                with self.assertRaisesRegex(ValueError, "must be a string"):
                    build_entry(repo, "a" * 40, payload)

    def test_normalization_rejects_null_boolean_and_nonfinite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            normalize_dependencies({"packs": [True]})
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            normalize_dependencies({"python_version": False})
        with self.assertRaisesRegex(ValueError, "array or object"):
            normalize_dependencies(None)
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            normalize_meta({"extension": float("nan")})
        with self.assertRaisesRegex(ValueError, "values must be unique"):
            normalize_meta({"tested_attune_versions": ["0.3.0", "0.3.0"]})
        with self.assertRaisesRegex(ValueError, "Invalid JSON constant"):
            json.loads('{"meta": {"extension": NaN}}', parse_constant=reject_json_constant)

        payload = archive(
            {
                "pack.yaml": b"""
ref: malformed
version: 1.0.0
label: null
name: Fallback must not win
"""
            }
        )
        repo = {
            "full_name": "attune-packs/malformed",
            "html_url": "https://github.com/attune-packs/malformed",
            "description": None,
            "default_branch": "main",
            "stargazers_count": 0,
            "license": None,
            "owner": {"login": "attune-packs"},
        }
        with self.assertRaisesRegex(ValueError, "label must be a string"):
            build_entry(repo, "a" * 40, payload)

    def test_keyword_precedence_uses_canonical_tags_then_legacy_fallbacks(self) -> None:
        metadata = {"keywords": ["meta"]}
        self.assertEqual(
            manifest_keywords(
                {"tags": ["tag"], "keywords": ["legacy"]},
                metadata,
            ),
            ["tag"],
        )
        self.assertEqual(manifest_keywords({"keywords": ["legacy"]}, metadata), ["legacy"])
        self.assertEqual(manifest_keywords({}, metadata), ["meta"])
        self.assertEqual(manifest_keywords({"tags": []}, metadata), [])

    def test_standard_policy_requires_sorted_immutable_entries(self) -> None:
        index = {
            "last_updated": "2026-08-15T00:00:00Z",
            "packs": [
                {
                    "ref": "demo",
                    "repository": "https://github.com/attune-packs/demo",
                    "contents": {"actions": []},
                    "install_sources": [
                        {
                            "type": "git",
                            "url": "https://github.com/attune-packs/demo.git",
                            "ref": "main",
                            "checksum": f"sha256:{'0' * 64}",
                        }
                    ],
                }
            ],
        }
        self.assertIn("demo: standard Git source must use one immutable commit SHA", validate_policy(index))

    def test_custom_policy_requires_immutable_git_commit_shas(self) -> None:
        index = {
            "last_updated": "2026-08-15T00:00:00Z",
            "packs": [
                {
                    "ref": "demo",
                    "contents": {"actions": []},
                    "install_sources": [
                        {
                            "type": "git",
                            "url": "https://example.com/demo.git",
                            "ref": "main",
                            "checksum": f"sha256:{'0' * 64}",
                        }
                    ],
                }
            ],
        }
        self.assertIn(
            "demo: Git sources must use immutable 40-character commit SHAs",
            validate_policy(index, standard=False),
        )

    def test_atomic_write_preserves_existing_file_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.json"
            path.write_text("old\n", encoding="utf-8")

            self.assertFalse(atomic_write_text(path, "old\n"))
            with mock.patch("build_index.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(list(path.parent.glob(".index.json.*.tmp")), [])

    def test_policy_rejects_forbidden_source_url_parts_and_allows_at_in_paths(self) -> None:
        invalid_urls = {
            "query": "https://example.com/demo.tar.gz?token=secret",
            "fragment": "https://example.com/demo.tar.gz#main",
            "username": "https://user@example.com/demo.tar.gz",
            "username and password": "https://user:pass@example.com/demo.tar.gz",
        }
        expected_error = (
            "demo: install source URLs must not contain credentials, query strings, or fragments"
        )

        for source_type in ("git", "archive"):
            for case, url in invalid_urls.items():
                source = {
                    "type": source_type,
                    "url": url,
                    "checksum": f"sha256:{'0' * 64}",
                }
                if source_type == "git":
                    source["ref"] = "a" * 40
                index = {
                    "last_updated": "2026-08-15T00:00:00Z",
                    "packs": [
                        {
                            "ref": "demo",
                            "contents": {"actions": []},
                            "install_sources": [source],
                        }
                    ],
                }

                with self.subTest(source_type=source_type, case=case):
                    self.assertIn(expected_error, validate_policy(index, standard=False))

            source["url"] = "https://example.com/releases/@scope/demo.tar.gz"
            with self.subTest(source_type=source_type, case="at in path"):
                self.assertNotIn(expected_error, validate_policy(index, standard=False))

    def test_policy_and_schema_reject_forbidden_registry_url_parts(self) -> None:
        schema_path = pathlib.Path(__file__).parents[1] / "schema" / "index.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(
            schema["properties"]["registry_url"],
            format_checker=jsonschema.FormatChecker(),
        )
        invalid_urls = [
            "https://user@example.com/index.json",
            "https://example.com/index.json?token=secret",
            "https://example.com/index.json#published",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertTrue(list(validator.iter_errors(url)))
                self.assertIn(
                    "registry_url must not contain credentials, query strings, or fragments",
                    validate_policy(
                        {
                            "registry_url": url,
                            "last_updated": "2026-08-17T00:00:00Z",
                            "packs": [],
                        },
                        standard=False,
                    ),
                )

        allowed = "https://example.com/releases/@scope/index.json"
        self.assertFalse(list(validator.iter_errors(allowed)))

    def test_schema_rejects_forbidden_source_url_parts_and_allows_at_in_paths(self) -> None:
        schema_path = pathlib.Path(__file__).parents[1] / "schema" / "index.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(
            schema["$defs"]["installSource"],
            format_checker=jsonschema.FormatChecker(),
        )
        invalid_urls = {
            "query": "https://example.com/demo.tar.gz?token=secret",
            "fragment": "https://example.com/demo.tar.gz#main",
            "username": "https://user@example.com/demo.tar.gz",
            "username and password": "https://user:pass@example.com/demo.tar.gz",
        }

        for source_type in ("git", "archive"):
            for case, url in invalid_urls.items():
                source = {
                    "type": source_type,
                    "url": url,
                    "checksum": f"sha256:{'0' * 64}",
                }
                if source_type == "git":
                    source["ref"] = "a" * 40

                with self.subTest(source_type=source_type, case=case):
                    self.assertTrue(list(validator.iter_errors(source)))

            source["url"] = "https://example.com/releases/@scope/demo.tar.gz"
            with self.subTest(source_type=source_type, case="at in path"):
                self.assertFalse(list(validator.iter_errors(source)))

    def test_partial_update_removes_old_ref_for_same_repository(self) -> None:
        repository = "https://github.com/attune-packs/demo"
        existing = {"old-demo": {"ref": "old-demo", "repository": repository}}
        generated = {"demo": {"ref": "demo", "repository": repository}}
        self.assertEqual(
            merge_entries(existing, generated, {repository}, partial=True),
            generated,
        )

    def test_partial_update_rejects_ref_owned_by_another_repository(self) -> None:
        existing = {
            "demo": {
                "ref": "demo",
                "repository": "https://github.com/attune-packs/original",
            }
        }
        generated = {
            "demo": {
                "ref": "demo",
                "repository": "https://github.com/attune-packs/replacement",
            }
        }
        with self.assertRaisesRegex(ValueError, "already owned"):
            merge_entries(
                existing,
                generated,
                {"https://github.com/attune-packs/replacement"},
                partial=True,
            )


if __name__ == "__main__":
    unittest.main()
