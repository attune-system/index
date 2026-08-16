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

## Hosting

Any HTTPS endpoint that returns `index.json` without authentication redirects
is suitable for a public index. Raw GitHub content is sufficient:

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
HTTPS host and an authentication design supported by the installer. Do not
assume that making only `index.json` private also makes public Git install
sources private.

## Non-GitHub Sources

The schema does not require GitHub. A custom producer may write the same JSON
contract using other source control or artifact systems. It must still:

- Use HTTPS URLs allowed by the consuming Attune deployment.
- Pin Git sources to immutable refs.
- Calculate Git checksums with Attune's directory checksum algorithm.
- Calculate archive checksums over the downloaded archive bytes.
- Emit component arrays, not component counts.
- Keep pack refs unique and deterministically ordered.
