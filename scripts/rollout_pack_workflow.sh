#!/usr/bin/env bash
set -euo pipefail

org="attune-packs"
apply=false
workflow_path=".github/workflows/publish-pack-index.yml"
template="templates/publish-pack-index.yml"

if [[ "${1:-}" == "--apply" ]]; then
  apply=true
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--apply]" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v base64 >/dev/null || { echo "base64 is required" >&2; exit 1; }
[[ -f "$template" ]] || { echo "run from the index repository root" >&2; exit 1; }

content=$(base64 -w 0 "$template")
gh repo list "$org" --limit 100 --source --no-archived --json nameWithOwner,defaultBranchRef \
  --jq '.[] | [.nameWithOwner, .defaultBranchRef.name] | @tsv' |
while IFS=$'\t' read -r repository branch; do
  if gh api "repos/$repository/contents/$workflow_path" >/dev/null 2>&1; then
    echo "skip $repository: workflow already exists"
    continue
  fi
  if [[ "$apply" != true ]]; then
    echo "would add $workflow_path to $repository@$branch"
    continue
  fi
  gh api --method PUT "repos/$repository/contents/$workflow_path" \
    -f message="Add standard pack index publishing" \
    -f content="$content" \
    -f branch="$branch" >/dev/null
  echo "added $workflow_path to $repository@$branch"
done
