# Publishing Packs to the Standard Index

## Onboarding

The standard index includes eligible repositories in `attune-packs`
automatically during its scheduled full sync. The per-pack workflow shortens
the delay after a push to `main`.

1. Create a fine-grained machine-user token whose resource owner is
   `attune-system`, whose only selected repository is `index`, and whose
   repository permission is `Contents: Read and write`. This permission is
   required by GitHub's repository dispatch endpoint.
2. Store it as the `ATTUNE_INDEX_TOKEN` organization Actions secret in
   `attune-packs`, scoped to the pack repositories.
3. Add `templates/publish-pack-index.yml` to each pack as
   `.github/workflows/publish-pack-index.yml`.
4. Run the caller workflow once or push to `main`.
5. Confirm the `Sync index` run in `attune-system/index`, then validate the
   pack with `attune pack index show PACK_REF` against an Attune instance that
   has the index configured.

The token is only consumed by the reusable workflow to send a
`repository_dispatch` event. Index generation and commits run in the index
repository under its own `GITHUB_TOKEN`.

## Bulk Rollout

Preview repositories that do not have the caller workflow:

```sh
./scripts/rollout_pack_workflow.sh
```

After the organization secret exists and the preview is reviewed, add the
workflow directly to each default branch:

```sh
./scripts/rollout_pack_workflow.sh --apply
```

The rollout script is intentionally dry-run by default. If protected branches
are enabled, use the template in normal pull requests instead of `--apply`.

## Pack Requirements

The root `pack.yaml` should provide:

```yaml
ref: example
label: Example
description: What the pack automates
version: "1.0.0"
author: Example Team
email: team@example.com
runtime_deps: [python]
tags: [example, integration]
dependencies: []
meta:
  category: integration
  license: Apache-2.0
  documentation_url: https://github.com/attune-packs/example
  repository_url: https://github.com/attune-packs/example
```

The repository must not contain symbolic links because Attune rejects links
during checksum and installation safety checks.

## Updating a Pack

Update `pack.yaml.version` in the same commit as the corresponding behavior
change. A push to `main` requests an index upsert. The published install source
uses that exact commit even though the pack's semantic version is read from
the manifest.

If publishing fails:

1. Inspect the pack's `Publish to standard pack index` workflow for dispatch
   authentication failures.
2. Inspect the index repository's `Sync index` workflow for manifest, archive,
   duplicate-ref, schema, or policy errors.
3. Run `python scripts/build_index.py --repository OWNER/REPOSITORY` locally
   with `GITHUB_TOKEN` set to reproduce the generation failure.
4. Fix the source pack. Do not manually patch its generated index entry.

## Release-Based Publishing

The initial standard index tracks immutable default-branch commits because the
pack organization does not yet have a consistent GitHub Release baseline. A
future release policy can switch eligibility to tags only after all packs:

- Use one tag convention, preferably `vMAJOR.MINOR.PATCH`.
- Ensure the tag version matches `pack.yaml.version`.
- Run pack checks and tests before release creation.
- Publish deterministic assets or continue using GitHub source archives.
- Define prerelease and rollback behavior.

That migration should be organization-wide rather than mixing mutable branch
and release policies without clearly exposing pack maturity.
