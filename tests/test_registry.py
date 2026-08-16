from __future__ import annotations

import hashlib
import io
import pathlib
import sys
import tarfile
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))

from build_index import attune_directory_checksum, build_entry, merge_entries, unpack_github_archive
from validate_index import validate_policy


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
description: A useful pack
version: 1.2.3
author: Attune
runtime_deps: [python]
tags: [example, demo]
dependencies: [core]
meta:
  category: examples
  license: Apache-2.0
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
        self.assertEqual(entry["keywords"], ["demo", "example"])
        self.assertEqual(entry["dependencies"], {"packs": ["core"]})
        self.assertEqual(entry["contents"]["actions"][0]["name"], "hello")
        self.assertEqual(entry["contents"]["workflows"][0]["name"], "deploy")
        self.assertEqual(entry["install_sources"][0]["ref"], "a" * 40)

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
