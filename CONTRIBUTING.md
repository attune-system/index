# Contributing

`index.json` is generated. Do not edit pack entries by hand.

## Pack Metadata Changes

Change the pack repository's `pack.yaml` or component metadata, then let its
publishing workflow request an index refresh. If that workflow has not been
installed, run the standard index's `Sync index` workflow manually.

## Tooling Changes

1. Install `requirements.txt` in a Python 3.11 or newer environment.
2. Update the builder, validator, schema, documentation, or workflows.
3. Run `python -m unittest discover -s tests -v`.
4. Run `python scripts/validate_index.py`.
5. Rebuild with `GITHUB_TOKEN="$(gh auth token)" python scripts/build_index.py`
   when the generated output should change.

Changes to index semantics must stay compatible with the `PackIndex` and
`PackIndexEntry` types in `attune-system/attune` or be coordinated with a new
index format version.
