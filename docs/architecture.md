# Architecture

## Goals

- Publish one deterministic, machine-readable index for public Attune packs.
- Keep pack source repositories authoritative for pack metadata and contents.
- Pin every install source to immutable content and verify it before install.
- Allow any GitHub organization to reuse the builder for a custom index.
- Avoid requiring write credentials for the index repository in every pack
  repository's workflow implementation.

## Data Flow

```text
attune-packs repository push
        |
        | reusable workflow + ATTUNE_INDEX_TOKEN
        v
repository_dispatch: pack-updated
        |
        v
attune-system/index sync workflow
        |
        | GitHub API metadata + commit-pinned source archive
        v
build_index.py -> validate_index.py -> index.json
        |
        v
raw.githubusercontent.com -> Attune registry client
```

The scheduled sync is the recovery path if a pack does not yet have the caller
workflow, a dispatch is missed, or a repository is archived or removed. A
dispatch performs a partial upsert; a scheduled or manual full sync also
removes packs that no longer satisfy the inclusion policy.

## Inclusion Policy

A standard-index repository must:

- Belong to `attune-packs`.
- Be public, non-archived, and not a fork.
- Contain `pack.yaml` at the repository root.
- Declare a unique pack `ref` and semantic `version`.
- Contain no symbolic links or other non-regular archive entries, matching the
  Attune installer's safety policy.
- Produce an entry that passes `schema/index.schema.json` and semantic policy
  validation.

A single invalid eligible repository fails the build. The previous valid index
remains published instead of silently dropping the broken pack.

## Source Integrity

GitHub's source archive for an exact commit is used as the canonical snapshot.
The builder computes:

- The archive's normal SHA-256 for the `archive` source.
- Attune's framed, sorted, path-and-content directory SHA-256 for the `git`
  source. This matches a clone after Attune removes `.git`.

The Git source and archive source are both pinned to the same 40-character
commit. Branch names are never published as install refs.

## Metadata Normalization

The builder supports the canonical manifest layout and common existing pack
layouts:

- `label`, with `name` and pack ref as fallbacks.
- `meta.license`, `meta.keywords`, and `meta.documentation_url` when equivalent
  top-level fields are absent.
- List-form `dependencies`, normalized to the index's `{ "packs": [...] }`
  representation.
- Canonical workflow action metadata in `actions/` identified by
  `workflow_file`, plus legacy top-level `workflows/` metadata.

Repository URL, commit, default branch, and star count come from GitHub rather
than potentially stale manifest values.

## Versioning

`version: "1.0"` is the index format version, not an Attune product version.
Breaking field changes require a new format version and coordinated Attune
client support. Adding optional metadata should remain compatible with the
existing Rust structures and this repository's schema.

## Operating Contract

The trigger guarantees, maintainer responsibilities, credential boundary,
failure behavior, and repository lifecycle are defined in
[Standard Index Automation Contract](automation-contract.md).
