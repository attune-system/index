# Standard Index Automation Contract

This document defines the operating contract between the standard index,
participating pack repositories, and their maintainers. It describes deployed
behavior, not a future release design.

## Scope

The standard index publishes public packs from `attune-packs` at:

```text
https://raw.githubusercontent.com/attune-system/index/main/index.json
```

The current publishing model tracks the root `pack.yaml` and complete Git tree
at each repository's latest `main` commit. It does not require a tag or GitHub
Release. The semantic pack version still comes from `pack.yaml.version`.

## Responsibilities

| Owner | Responsibilities |
| --- | --- |
| Pack maintainer | Keep `pack.yaml` and component metadata valid, update the semantic version with behavior changes, keep the publishing workflow present, and investigate failures caused by pack content. |
| `attune-packs` organization admin | Maintain `ATTUNE_INDEX_TOKEN`, control which repositories receive it, and remove access from repositories that leave the standard catalog. |
| Index maintainer | Maintain the schema, builder, validator, reusable workflow, scheduled sync, and published index availability. |
| Attune deployment admin | Configure index order and approved hosts, retain checksum verification, and decide which indices are trusted. |

Pack repositories are the source of truth for pack content. `index.json` is a
generated artifact and must not be edited to work around source metadata or
validation failures.

## Trigger and Update Flow

Every participating pack contains
`.github/workflows/publish-pack-index.yml`. A push to `main` or a manual run:

1. Calls `attune-system/index/.github/workflows/publish-pack.yml@main`.
2. Reads the `ATTUNE_INDEX_TOKEN` organization Actions secret.
3. Sends a `pack-updated` repository dispatch to `attune-system/index` with the
   caller repository, Git ref, and commit SHA.
4. Starts `Sync index` in the index repository.
5. Re-reads the requested repository from GitHub, resolves its current default
   branch commit, generates its entry, and validates the complete index.
6. Commits `index.json` only when generated content changed.

The dispatch payload is a refresh request, not authoritative metadata. The
central builder obtains repository state directly from GitHub and never trusts
the caller to provide pack fields or checksums.

## Scheduled Reconciliation

`Sync index` also runs every six hours and can be started manually. These runs
perform a full organization scan rather than a partial upsert.

The full sync is authoritative for membership. It:

- Adds newly eligible public, non-fork, non-archived repositories.
- Refreshes every entry from the repository's current default branch.
- Removes repositories that were deleted, archived, forked, or moved out of
  the organization.
- Detects duplicate pack refs across the complete organization.

GitHub Actions concurrency serializes index writes. During a burst of pack
updates, GitHub may coalesce pending dispatch-triggered runs. This is expected:
the scheduled full sync is the recovery and reconciliation mechanism. Do not
assume there will be one index commit for every pack commit.

## Publication Guarantees

For every successfully published entry, the automation guarantees:

- The pack was read from a specific 40-character Git commit.
- The Git source is pinned to that commit.
- The Git checksum uses Attune's deterministic path-and-content directory
  checksum and excludes Git metadata.
- The archive source is pinned to the same commit and carries the downloaded
  archive's SHA-256.
- Component summaries are arrays of names and descriptions, not counts.
- The complete index passed JSON Schema and semantic policy validation before
  it was committed.
- Pack refs are unique and entries are sorted by ref.

The automation does not guarantee that external services used by a pack are
available, that credentials are configured, or that every action succeeds in
a consumer's environment. Pack tests and deployment-specific validation remain
separate responsibilities.

## Failure Behavior

Generation fails closed. If one eligible pack cannot be fetched or validated,
the automation does not publish a partial full index. Consumers continue to
receive the previous valid `index.json`.

Expected investigation order:

1. Inspect the pack's `Publish to standard pack index` caller run.
2. If dispatch succeeded, inspect the corresponding index `Sync index` run.
3. Reproduce one-pack generation with:

   ```sh
   GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
     --repository attune-packs/PACK
   python scripts/validate_index.py
   ```

4. Fix the source pack or central tooling as appropriate.
5. Re-run the caller workflow for a partial refresh, or run `sync.yml` manually
   for authoritative full reconciliation.

Do not disable validation, hand-edit checksums, or remove a failing entry from
`index.json` while its source repository remains eligible.

## Credential Contract

`ATTUNE_INDEX_TOKEN` is a fine-grained token with:

- Resource owner `attune-system`.
- Access only to the `index` repository.
- Repository permission `Contents: Read and write`.

It is stored as an `attune-packs` organization Actions secret and made
available only to participating pack repositories. It is used solely to call
GitHub's repository dispatch endpoint. Pack workflows never clone, modify, or
push the index repository with this token.

The central sync uses the index repository's short-lived `GITHUB_TOKEN` to read
public sources and commit generated changes. No personal access token is
stored in the index repository.

During token rotation, scheduled full syncs continue to work. Immediate pack
dispatches may fail until the organization secret is replaced. Validate a
single caller and its corresponding index run before revoking the previous
token.

## Repository Lifecycle

For a new standard pack:

1. Create a public, non-fork repository in `attune-packs` with root
   `pack.yaml`.
2. Ensure the repository receives the `ATTUNE_INDEX_TOKEN` organization
   secret.
3. Add `templates/publish-pack-index.yml` as
   `.github/workflows/publish-pack-index.yml`.
4. Run pack checks and tests.
5. Push to `main` and verify both caller and index workflows.
6. Confirm the pack appears in the hosted index and through
   `attune pack index show PACK_REF`.

For removal, archive or delete the source repository, move it out of
`attune-packs`, or explicitly change the standard inclusion policy. A full sync
removes it. Removing only the caller workflow does not remove the pack because
scheduled discovery remains authoritative.

## Change Control

Changes to required fields, checksum meaning, source selection, or index
version require coordinated review with the Attune registry parser and
installer. The canonical contracts are:

- `schema/index.schema.json` in this repository.
- `PackIndex`, `PackIndexEntry`, and related types in
  `attune-system/attune`.
- The [custom index user guide](https://github.com/attune-system/attune/wiki/Custom-Pack-Indices).

Backward-compatible metadata additions still require schema, builder,
validator, tests, and documentation updates in the same change.

## Routine Verification

Index maintainers should periodically verify:

- The most recent scheduled sync succeeded within the expected six-hour
  interval.
- `index.json.last_updated` advances when pack content changes.
- A caller-workflow pilot dispatch succeeds after credential rotation.
- A full sync produces one entry per eligible repository.
- A representative pack can be browsed and installed from a test Attune
  deployment with checksum verification enabled.

See [Operations](operations.md) for commands and [Pack Publishing](pack-publishing.md)
for onboarding details.
