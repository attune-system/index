#!/usr/bin/env bash
set -euo pipefail

org="attune-packs"
apply=false
workflow_path=".github/workflows/publish-pack-index.yml"
repository_root=$(pwd)
template="$repository_root/templates/publish-pack-index.yml"

if [[ "${1:-}" == "--apply" ]]; then
  apply=true
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--apply]" >&2
  exit 2
fi

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
[[ -f "$template" ]] || { echo "run from the index repository root" >&2; exit 1; }

rollout_root=$(mktemp -d "${TMPDIR:-/tmp}/attune-index-rollout.XXXXXX")
trap 'rm -rf "$rollout_root"' EXIT

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

  checkout="$rollout_root/${repository#*/}"
  git clone --quiet --depth 1 --branch "$branch" "git@github.com:$repository.git" "$checkout"
  mkdir -p "$checkout/.github/workflows"
  cp "$template" "$checkout/$workflow_path"
  git -C "$checkout" add "$workflow_path"
  git -C "$checkout" commit --quiet -m "Add standard pack index publishing"
  git -C "$checkout" push --quiet origin "$branch"
  echo "added $workflow_path to $repository@$branch"
done
