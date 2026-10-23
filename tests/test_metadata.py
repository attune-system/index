from __future__ import annotations

import pathlib
import sys
import json
import tempfile
import unittest
from typing import Any
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))

from build_index import build_entry
from refresh_pinned_metadata import main as refresh_metadata_main, refresh_entry
from test_registry import archive


REPOSITORY = {
    "full_name": "attune-packs/demo",
    "html_url": "https://github.com/attune-packs/demo",
    "default_branch": "main",
    "owner": {"login": "attune-packs"},
    "license": None,
}

# Both example packs explicitly declare MIT but have truncated disclaimers.
MIT_LICENSE = b"""MIT License

Copyright (c) 2025 Attune Automation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR
"""


def entry(
    files: dict[str, bytes], manifest: bytes = b"", **repo_metadata: Any
) -> dict[str, Any]:
    return build_entry(
        {**REPOSITORY, **repo_metadata},
        "a" * 40,
        archive({"pack.yaml": b"ref: demo\nversion: 1.0.0\n" + manifest, **files}),
    )


class MetadataTests(unittest.TestCase):
    def test_infers_azure_python_script_runtime(self) -> None:
        result = entry({
            "actions/list.yaml": b"runner_type: python-script\nentry_point: azure_action.py\n",
            "requirements.txt": b"azure-identity==1.25.3\n",
        })
        self.assertEqual(result["runtime_deps"], ["python"])

    def test_infers_supported_runner_aliases_case_insensitively(self) -> None:
        aliases = {
            "python": ("python", "python3", "python-script", "core.python"),
            "nodejs": ("node", "nodejs", "Node.js", "nodejs-script", "core.nodejs"),
            "shell": ("shell", "sh", "bash", "shell-script", "core.shell"),
        }
        for runtime, names in aliases.items():
            for name in names:
                with self.subTest(name=name):
                    result = entry({"actions/run.yml": f"runner_type: {name}\n".encode()})
                    self.assertEqual(result["runtime_deps"], [runtime])

    def test_inference_uses_sensors_and_inline_components_and_sorts(self) -> None:
        result = entry(
            {"sensors/watch.yaml": b"runner_type: python3\n"},
            b"actions:\n  one:\n    runner_type: bash\n  two:\n    runner_type: node\n",
        )
        self.assertEqual(result["runtime_deps"], ["nodejs", "python", "shell"])

    def test_declared_runtime_dependencies_remain_authoritative(self) -> None:
        for declared, expected in ((b"[]", []), (b"[python3, 'python3>=3.11']", ["python3", "python3>=3.11"])):
            with self.subTest(declared=declared):
                result = entry(
                    {"actions/run.yaml": b"runner_type: python-script\n"},
                    b"runtime_deps: " + declared + b"\n",
                )
                self.assertEqual(result["runtime_deps"], expected)

    def test_does_not_infer_from_workflow_graphs_scripts_or_unknown_runners(self) -> None:
        result = entry({
            "actions/flow.yaml": b"runner_type: python\nworkflow_file: workflows/flow.yaml\n",
            "actions/workflows/flow.yaml": b"runner_type: node\n",
            "actions/custom.yaml": b"runner_type: vendor.python\n",
            "actions/native.yaml": b"runner_type: native\n",
            "examples/run.py": b"print('example')\n",
        })
        self.assertEqual(result["runtime_deps"], [])

    def test_file_components_take_precedence_over_inline_components(self) -> None:
        result = entry(
            {"actions/run.yaml": b"runner_type: python\n"},
            b"actions:\n  ignored:\n    runner_type: node\n",
        )
        self.assertEqual(result["runtime_deps"], ["python"])

    def test_inference_rejects_non_string_runner_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "runner_type must be a string"):
            entry({"actions/run.yaml": b"runner_type: [python]\n"})

    def test_uses_explicit_mit_license_in_pinned_root_license_files(self) -> None:
        for name in ("LICENSE", "LICENSE.md", "license.txt", "LICENCE", "COPYING"):
            with self.subTest(name=name):
                self.assertEqual(entry({name: MIT_LICENSE})["license"], "MIT")

    def test_manifest_license_takes_precedence_over_license_file(self) -> None:
        for manifest in (b"license: Apache-2.0\n", b"meta:\n  license: Apache-2.0\n"):
            with self.subTest(manifest=manifest):
                self.assertEqual(entry({"LICENSE": MIT_LICENSE}, manifest)["license"], "Apache-2.0")

    def test_pinned_license_takes_precedence_over_unpinned_api_metadata(self) -> None:
        result = entry({"LICENSE": MIT_LICENSE}, license={"spdx_id": "Apache-2.0"})
        self.assertEqual(result["license"], "MIT")

    def test_does_not_assign_license_from_dependencies_or_mentions(self) -> None:
        for files in ({}, {"vendor/lib/LICENSE": MIT_LICENSE}, {"README.md": MIT_LICENSE}, {"LICENSE": b"This project uses MIT License dependencies."}, {"LICENSE": b"MIT License\n"}):
            with self.subTest(files=list(files)):
                self.assertEqual(entry(files)["license"], "NOASSERTION")

    def test_conflicting_root_license_files_are_not_classified_as_mit(self) -> None:
        self.assertEqual(
            entry({"LICENSE": MIT_LICENSE, "LICENSE.other": b"Custom terms\n"})["license"],
            "NOASSERTION",
        )

    def test_pinned_refresh_verifies_both_checksums_and_only_changes_derived_metadata(self) -> None:
        payload = archive({
            "pack.yaml": b"ref: demo\nversion: 1.0.0\n",
            "actions/run.yaml": b"runner_type: python-script\n",
            "LICENSE": MIT_LICENSE,
        })
        expected = build_entry({**REPOSITORY, "id": 42}, "a" * 40, payload)
        baseline = {**expected, "runtime_deps": [], "license": "NOASSERTION"}
        self.assertEqual(refresh_entry(baseline, payload), expected)
        for source_type in ("git", "archive"):
            tampered = {**baseline, "install_sources": [
                {**source, "checksum": "sha256:" + "0" * 64}
                if source["type"] == source_type else source
                for source in baseline["install_sources"]
            ]}
            with self.subTest(source_type=source_type):
                with self.assertRaisesRegex(ValueError, "protected fields: install_sources"):
                    refresh_entry(tampered, payload)

    def test_pinned_refresh_preserves_other_packs_and_is_idempotent(self) -> None:
        payload = archive({
            "pack.yaml": b"ref: demo\nversion: 1.0.0\n",
            "actions/run.yaml": b"runner_type: python-script\n",
        })
        expected = build_entry({**REPOSITORY, "id": 42}, "a" * 40, payload)
        untouched = {**expected, "ref": "untouched"}
        baseline = {
            "registry_name": "Attune Standard Pack Index",
            "registry_url": "https://github.com/attune-system/index",
            "version": "1.0",
            "last_updated": "2026-10-12T01:11:23Z",
            "packs": [{**expected, "runtime_deps": []}, untouched],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "published.json"
            output = pathlib.Path(directory) / "index.json"
            original = json.dumps(baseline)
            source.write_text(original, encoding="utf-8")
            with (
                mock.patch.object(sys, "argv", ["refresh_pinned_metadata.py", "--baseline", str(source), "--pack", "demo", "--output", str(output)]),
                mock.patch("refresh_pinned_metadata.github_request", return_value=payload) as request,
            ):
                self.assertEqual(refresh_metadata_main(), 0)
                first = output.read_bytes()
                self.assertEqual(refresh_metadata_main(), 0)
                self.assertEqual(output.read_bytes(), first)
            self.assertEqual(json.loads(first)["packs"], [expected, untouched])
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertEqual(request.call_count, 2)
            request.assert_called_with(expected["install_sources"][1]["url"])
