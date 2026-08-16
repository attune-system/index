# Operations

## Automation

`Sync index` runs every six hours, on manual dispatch, and on a
`pack-updated` repository dispatch. Runs are serialized to prevent concurrent
writes to `index.json`.

The workflow only commits when generated pack entries change. The
`last_updated` value is preserved on no-op builds, so scheduled runs do not
create timestamp-only commits.

The complete maintainer and pack-repository expectations are defined in the
[Standard Index Automation Contract](automation-contract.md).

## Required Repository Settings

- Enable GitHub Actions.
- Set workflow permissions to allow read and write, or retain the explicit
  `contents: write` grant in `sync.yml` under an organization policy that
  permits it.
- If `main` is protected, allow the sync workflow to update `index.json` or
  change the workflow to open a pull request.
- Keep `validate.yml` required for human-authored pull requests.
- Restrict administration of the cross-organization `ATTUNE_INDEX_TOKEN`.

No long-lived secret is required in the index repository for normal builds.
Its own `GITHUB_TOKEN` reads public pack metadata and writes the generated
index.

## Manual Recovery

Run a full rebuild from the repository root:

```sh
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py
python scripts/validate_index.py
```

Use a partial upsert for one pack:

```sh
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
  --repository attune-packs/slack
python scripts/validate_index.py
```

Trigger the hosted full sync with:

```sh
gh workflow run sync.yml --repo attune-system/index
```

## Failure Behavior

Generation is fail-closed. If any eligible pack cannot be fetched, contains an
unsafe archive member, has an invalid manifest, duplicates another pack ref,
or produces an invalid index entry, the workflow does not publish a new index.
Consumers continue using the previous valid file.

A partial dispatch does not remove entries. A successful full sync is required
to remove an archived or deleted repository.

## Observability

Use GitHub Actions run status as the initial operational signal. Recommended
follow-up controls are:

- A required successful scheduled run within the previous 24 hours.
- An alert when `last_updated` is unexpectedly old relative to pack changes.
- A smoke-test Attune instance that configures the raw index URL and exercises
  browse, show, and install against a small representative pack.
- Dependabot or equivalent monitoring for the two Python validation
  dependencies and GitHub Actions versions.

## Security Rotation

Rotate `ATTUNE_INDEX_TOKEN` as a normal machine credential. During rotation,
scheduled central sync remains functional; only immediate pack dispatches are
delayed. Replace the organization secret, run one pack caller workflow, and
confirm a corresponding dispatch-triggered index run before revoking the old
token.
