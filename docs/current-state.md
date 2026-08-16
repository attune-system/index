# Current State

The initial index build on 2026-08-15 discovered 44 eligible public
repositories in `attune-packs` and generated entries for all 44.

## Inventory

| Measure | Count |
| --- | ---: |
| Packs | 44 |
| Actions | 1,054 |
| Sensors | 11 |
| Triggers | 14 |
| Rules | 3 |
| Workflows | 2 |

Declared pack categories are currently:

| Category | Packs |
| --- | ---: |
| integration | 28 |
| infrastructure | 5 |
| monitoring | 3 |
| examples | 2 |
| data | 1 |
| identity | 1 |
| security | 1 |
| system | 1 |
| virtualization | 1 |
| uncategorized | 1 |

These counts are a bootstrap snapshot, not manually maintained registry
metadata. `index.json` is the current source of truth.

## Metadata Gaps

Four repositories do not currently declare a license in `pack.yaml` or expose
one through GitHub's license API:

- `attune`
- `nodejs_example`
- `python_example`
- `salesforce`

Their generated entries use the SPDX special value `NOASSERTION`. Each source
repository should add an explicit license before a policy is introduced to
reject undeclared licenses.

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
