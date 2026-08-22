# Building a Custom Index

The index format is decentralized. A team can publish its own index and place
it before or after the standard index in Attune's configured search order.

## GitHub Organization Index

Fork this repository or copy its schema, scripts, tests, and validation
workflow. Build an index for a public GitHub organization with:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
  --org example-packs \
  --registry-name "Example Pack Index" \
  --registry-url "https://github.com/example/index"

python scripts/validate_index.py --custom
```

The builder includes every public, non-archived, non-fork repository in the
organization. Use repeated `--repository owner/name` arguments to upsert a
specific subset into an existing index:

```sh
GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py \
  --repository example-packs/network \
  --repository example-packs/storage \
  --registry-name "Example Pack Index" \
  --registry-url "https://github.com/example/index"
```

Run a periodic full build even when event-driven partial updates are enabled;
only a full build removes repositories that have been archived or deleted.

Manifest normalization follows canonical Attune precedence: `label` before
`name`, `tags` before top-level `keywords` before `meta.keywords`, top-level
`license` before `meta.license`, and top-level `homepage` before
`meta.documentation_url`. Both list and object dependency declarations are
normalized to the index dependency object, and JSON-compatible manifest
`meta` fields are retained. Canonical scalar metadata must be strings; list and
dependency normalization accepts strings and finite numbers but rejects nulls,
booleans, objects, and non-finite values. Output replacement is atomic and an
unchanged rebuild leaves the existing file untouched.

Component summaries use top-level component YAML files when present and fall
back to inline `pack.yaml` component maps when no files exist for that type.
Component `ref`, `name`, `description`, `label`, and `workflow_file` metadata
must be strings; malformed values fail instead of being stringified or dropped.

## Hosting

Any HTTPS endpoint that returns `index.json` without authentication redirects
or query parameters is suitable for a public index. Raw GitHub content is
sufficient:

```text
https://raw.githubusercontent.com/OWNER/REPOSITORY/main/index.json
```

Configure every hostname used by the index and its install sources in
Attune's `pack_registry.approved_public_hosts`. For this builder's GitHub
sources, allow:

```yaml
pack_registry:
  approved_public_hosts:
    - raw.githubusercontent.com
    - github.com
    - codeload.github.com
```

Then add the index through the CLI:

```sh
attune pack index add \
  https://raw.githubusercontent.com/OWNER/REPOSITORY/main/index.json \
  --name "Example Pack Index"
```

Use `attune pack index list`, `attune pack index browse`, and
`attune pack index show PACK_REF` to confirm ordering and resolution.

## Private Indexes

Attune supports request headers for authenticated index URLs, but the current
Git installer intentionally rejects credential-bearing and SSH URLs. A private
index therefore also needs install artifacts reachable through an approved
HTTPS host without per-request credentials; archive downloads do not send
custom headers either. Do not assume that making only `index.json` private also
makes public Git install sources private. Query-authenticated or presigned index
and pack-source URLs are rejected so credentials cannot leak through logs, API
responses, or provenance records.

## Non-GitHub Sources

The schema does not require GitHub. A custom producer may write the same JSON
contract using other source control or artifact systems. It must still:

- Use HTTPS URLs allowed by the consuming Attune deployment.
- Pin every Git source to an immutable 40-character commit SHA. The maintained
  `--custom` validator enforces this production policy.
- Generate Git checksums with Attune's framed, sorted path-and-content directory
  algorithm. The maintained builder computes these only for GitHub entries.
- Calculate archive checksums over the downloaded archive bytes.
- Give each fallback archive its own SHA-256; Attune tries the first archive if
  the preferred Git source fails and records the checksum actually verified.
- Emit component arrays, not component counts.
- Keep pack refs unique and deterministically ordered.

Attune's local `index-entry` and `index-update` commands may accept a branch or
tag in `--git-ref` for development-only indices. That permissive CLI behavior
is not a production publishing contract: resolve the source revision first and
publish the lowercase 40-character commit SHA. In GitHub Actions, pass
`${{ github.sha }}`, never `${{ github.ref_name }}` or `main`.
