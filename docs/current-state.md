# Current State

The initial index build on 2026-08-15 discovered 44 eligible public
repositories in `attune-packs` and generated entries for all 44.

The 2026-10-23 audit correction uses the 47-pack published index dated
2026-10-12 as its baseline, preserving every published source pin and checksum.

## Inventory

| Measure | Count |
| --- | ---: |
| Packs | 47 |
| Actions | 1,080 |
| Sensors | 14 |
| Triggers | 17 |
| Rules | 4 |
| Workflows | 7 |

Declared pack categories are currently:

| Category | Packs |
| --- | ---: |
| integration | 30 |
| infrastructure | 5 |
| monitoring | 3 |
| examples | 2 |
| data | 1 |
| identity | 1 |
| security | 1 |
| system | 1 |
| testing | 1 |
| virtualization | 1 |
| uncategorized | 1 |

These counts describe the corrected 2026-10-23 snapshot, not manually maintained
registry metadata. `index.json` is the current source of truth.

## Metadata Gaps

The 2026-10-23 audit verified the exact local and public indexed archives for
the four entries originally marked `NOASSERTION`. `nodejs_example` and
`python_example` contain root `LICENSE` files with explicit MIT headings,
permission grants, and notice clauses. The builder now recognizes those
declarations, and their index licenses are `MIT`. Both upstream license files
end mid-disclaimer and should be completed by their maintainers.

The maintainer selected Apache 2.0 for `attune` and `salesforce`. Both source
repositories now publish a full `LICENSE` and `license: Apache-2.0` in
`pack.yaml`. Attune also preserves the generated client's upstream MIT and
BSD-3-Clause notices in `NOTICE`.

The new files change archive digests, so the index uses new patch versions
`attune` 0.2.1 and `salesforce` 0.1.1 rather than relabeling or replacing the
old immutable sources. Their entries are regenerated from their exact published
commits. No pack in the corrected index remains `NOASSERTION`. A dependency's
license does not license the containing pack.

The corrected entries use these published source commits:

| Pack | Commit | Correction |
| --- | --- | --- |
| `azure` | `8b477b248193751fc4c04bd06ac4bf1aef429a2a` | Infer `python` from its `python-script` actions |
| `nodejs_example` | `ceddb815995307794e3c43e673e9315481cdba7d` | Recognize the explicit MIT grant in `LICENSE` |
| `python_example` | `dfbdaabf2783745c1052e62eb0ecd64a741909d2` | Recognize the explicit MIT grant in `LICENSE` |
| `attune` | `ebe93dbc713a38ee3967f681432f65e4f15d4a6a` | Publish Apache-2.0 as version 0.2.1 with upstream notices |
| `salesforce` | `6997b57c367de8fa7a447b7ab3abdd92bfd7b12f` | Publish Apache-2.0 as version 0.1.1 |

Each correction was regenerated with `build_entry` from its exact published
pinned archive and published repository metadata. The
`scripts/refresh_pinned_metadata.py` tool rejects changes to any field except
`runtime_deps` and `license`, including either install-source checksum. It does
not query repository heads or current GitHub metadata. The saved published
baseline has SHA-256
`7b55ee641f68fcbaedb439c18267036cda9fd0693682a3d3c70ed8698943179f`.

Slack retains its public canonical 0.1.3 entry at
`f7bd31ad0b3c5fb228e0d82c000ef83f0a01b16b`, including `request_approval` and
`approval_example`, with nine total components. All 47 packs are preserved,
including `attune_validation`, `mattermost`, and `yt_dlp`. The three original
metadata corrections retain their source pins and checksums. Only `attune`
and `salesforce` move to new, explicitly published source versions, with newly
measured directory and archive checksums. The other 45 packs retain their
published source records.

To repeat the correction against a saved published baseline:

```sh
python scripts/refresh_pinned_metadata.py \
  --baseline /tmp/opencode/attune-published-index.json \
  --pack azure --pack nodejs_example --pack python_example \
  --output index.json
python scripts/validate_index.py
```

Then regenerate the two licensed patch releases through normal targeted index
publication, not the pinned-metadata correction tool:

```sh
python scripts/build_index.py --repository attune-packs/attune \
  --commit ebe93dbc713a38ee3967f681432f65e4f15d4a6a
python scripts/build_index.py --repository attune-packs/salesforce \
  --commit 6997b57c367de8fa7a447b7ab3abdd92bfd7b12f
python scripts/validate_index.py
```

One pack is currently categorized as `uncategorized`; its source manifest
should supply `meta.category`.

## Release Readiness

The organization does not yet have a consistent tag and GitHub Release
baseline. The initial index therefore publishes exact default-branch commit
snapshots. Moving to release-only publishing requires the organization-wide
controls listed in [Pack Publishing](pack-publishing.md#release-based-publishing).

## Rollout Status

The caller workflow was deployed to all 44 repositories on 2026-08-15. The
Slack pilot and every rollout-triggered caller run successfully consumed the
`ATTUNE_INDEX_TOKEN` organization secret and dispatched an index refresh. A
full post-rollout sync verified that all 44 indexed commits match their pack
repositories' `main` HEAD.

The dry-run mode in `scripts/rollout_pack_workflow.sh` now reports every
eligible repository as already configured. Keep the organization secret
available to all participating repositories and use the scheduled full sync as
the recovery path for missed or coalesced dispatch events.
