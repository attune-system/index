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
        | repository + exact 40-character commit SHA
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
dispatch performs a partial upsert from the commit in its payload. A scheduled
or manual full sync resolves current default-branch heads and also removes packs
that no longer satisfy the inclusion policy.

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

Use this repository's builder to produce the framed Git checksum rather than
reimplementing the byte framing independently. Archive checksums are always
SHA-256 over the exact downloaded bytes.

The Git source and archive source are both pinned to the same 40-character
commit. Branch names are never published as install refs.

The consumer prefers Git and falls back on failure to the first independently
checksummed archive source. For this standard index that makes
`codeload.github.com` a required approved source host. The installed
`pack.yaml` ref and version must match the selected entry.

## Metadata Normalization

The builder supports the canonical manifest layout and common existing pack
layouts. Alias fallback is based on field presence, so a declared canonical
field is authoritative even when a legacy alias is also present:

- `label`, then `name`, then pack ref.
- Discovery terms in canonical `tags`, then legacy top-level `keywords`, then
  `meta.keywords`. Values are deduplicated and sorted.
- Top-level `license`, then `meta.license`, then repository SPDX metadata.
- Top-level `homepage`, then `meta.documentation_url`.
- Top-level `use_case`, then `meta.use_case`.
- List-form `dependencies`, normalized to `{ "packs": [...] }`, and object-form
  dependencies normalized to the schema's `PackDependencies` fields.
- Manifest `meta` fields are preserved when they are JSON-compatible. The
  standard GitHub builder adds authoritative `default_branch`, `commit`,
  `repository_id`, and `stars` values. The stable repository ID lets partial
  updates replace an entry after a repository rename. Non-GitHub producers
  should not invent those fields.
- Canonical scalar metadata must be strings. Discovery, runtime, and dependency
  arrays accept strings and finite numbers; nulls, booleans, objects, and
  non-finite values fail generation.
- Canonical workflow action metadata in `actions/` identified by
  `workflow_file`, plus legacy top-level `workflows/` metadata.
- Inline component maps are inventoried when a component type has no top-level
  YAML files. Component refs, names, descriptions, labels, and workflow-file
  values must be strings; malformed metadata fails generation.

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
