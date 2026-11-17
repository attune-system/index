"""Offline regression coverage for generated PRs and tested-head reporting."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parent.parent
SYNC = yaml.safe_load((ROOT / ".github/workflows/sync.yml").read_text())
VALIDATE = yaml.safe_load((ROOT / ".github/workflows/validate.yml").read_text())


class AutomationTests(unittest.TestCase):
    def test_generated_changes_go_to_an_isolated_pr_not_main(self):
        job = SYNC["jobs"]["sync"]
        self.assertFalse(any("git push" in step.get("run", "") for step in job["steps"]))
        publisher = next(step for step in job["steps"] if step.get("id") == "pull-request")
        self.assertTrue(publisher["uses"].startswith("peter-evans/create-pull-request@"))
        self.assertEqual(publisher["with"]["base"], "main")
        self.assertEqual(publisher["with"]["add-paths"], "index.json")
        self.assertIn("github.run_id", publisher["with"]["branch"])
        self.assertIn("github.run_attempt", publisher["with"]["branch"])

    def test_validator_checks_out_the_reported_head_with_read_only_access(self):
        verifier = SYNC["jobs"]["verify"]
        self.assertEqual(verifier["uses"], "./.github/workflows/validate.yml")
        self.assertEqual(verifier["with"]["ref"], "${{ needs.sync.outputs.head-sha }}")
        self.assertEqual(verifier["permissions"], {"contents": "read"})
        self.assertIn("needs.sync.outputs.pr-number != ''", verifier["if"])
        self.assertEqual(VALIDATE["permissions"], {"contents": "read"})
        self.assertEqual(VALIDATE["jobs"]["validate"]["name"], "Index validation")
        checkout = VALIDATE["jobs"]["validate"]["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "${{ inputs.ref || github.sha }}")
        self.assertFalse(checkout["with"]["persist-credentials"])
        reporter = SYNC["jobs"]["report-validation"]
        self.assertEqual(reporter["permissions"], {"checks": "write"})
        self.assertEqual(reporter["needs"], ["sync", "verify"])
        self.assertIn("always()", reporter["if"])
        self.assertIn("needs.sync.outputs.head-sha != ''", reporter["if"])
        self.assertIn("needs.sync.outputs.pr-number != ''", reporter["if"])
        self.assertFalse(any("uses" in step for step in reporter["steps"]))

    def test_reporter_records_the_actual_result_on_the_exact_tested_commit(self):
        step = SYNC["jobs"]["report-validation"]["steps"][0]
        self.assertEqual(step["env"]["HEAD_SHA"], "${{ needs.sync.outputs.head-sha }}")
        self.assertEqual(step["env"]["VALIDATION_RESULT"], "${{ needs.verify.result }}")
        for result in ("success", "failure", "cancelled", "skipped", "unexpected"):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                capture = root / "request"
                gh = root / "gh"
                gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE.args"\ncat > "$CAPTURE"\n')
                gh.chmod(0o700)
                completed = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", step["run"]],
                    env={"PATH": str(root) + os.pathsep + os.defpath,
                         "CAPTURE": str(capture), "GH_TOKEN": "fixture-token",
                         "HEAD_SHA": "a" * 40, "VALIDATION_RESULT": result,
                         "CHECK_NAME": "Index validation", "GITHUB_RUN_ID": "123",
                         "GITHUB_SERVER_URL": "https://github.example.invalid",
                         "GITHUB_REPOSITORY": "fixture/index"},
                    capture_output=True, text=True, timeout=10,
                )
                if result == "unexpected":
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertFalse(capture.exists())
                    continue
                self.assertEqual(completed.returncode, 0, completed.stderr)
                request = json.loads(capture.read_text())
                self.assertEqual(request["head_sha"], "a" * 40)
                self.assertEqual(request["name"], "Index validation")
                self.assertEqual(request["conclusion"], "success" if result == "success" else "failure")
                self.assertEqual(request["status"], "completed")
                self.assertEqual(capture.with_suffix(".args").read_text().splitlines(), [
                    "api", "--method", "POST", "repos/fixture/index/check-runs", "--input", "-",
                ])


if __name__ == "__main__":
    unittest.main()
