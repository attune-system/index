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
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py --skip-invalid
python scripts/validate_index.py
```

Omit `--skip-invalid` for a strict local rebuild that stops at the first invalid
repository. The hosted scheduled/manual full sync uses the tolerant mode.

Use a partial upsert for one pack:

```sh
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
  --repository attune-packs/slack
python scripts/validate_index.py
```

To reproduce a dispatch exactly, pin its repository and commit together:

```sh
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
  --repository attune-packs/slack \
  --commit 0123456789abcdef0123456789abcdef01234567
python scripts/validate_index.py
```

`--commit` accepts only a lowercase 40-character hexadecimal SHA on the
repository's current default branch and requires exactly one `--repository`.
The builder ignores a delayed dispatch when the index already contains a newer
commit. Without `--commit`, partial and full local builds resolve the current
default-branch head.

Trigger the hosted full sync with:

```sh
gh workflow run sync.yml --repo attune-system/index
```

## Failure Behavior

Full syncs skip repositories that cannot be fetched, contain unsafe archives or
invalid metadata, or produce invalid index entries. They retain the repository's
last published entry when available, otherwise omit it. Duplicate refs reject
all conflicting new entries. Healthy pack updates continue, and warnings plus the
job summary identify skipped repositories and whether old entries were retained.

Targeted publishing remains fail-closed so an invalid requested update reports
failure. Discovery errors, unexpected programming errors, and invalid final
index state still block publication; the complete output is always validated.

A partial dispatch does not remove entries. A successful full sync is required
to remove an archived or deleted repository.

## Observability

Use GitHub Actions run status as the initial operational signal. Recommended
follow-up controls are:

- A required successful scheduled run within the previous 24 hours.
- Review warning annotations and the job summary for skipped repositories, even
  when the run succeeded.
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
