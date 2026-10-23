#!/bin/bash
# Publishes a distribution tree (go run ./tools dist) to the distribution
# repository: one commit on main with exactly the tree's content, and one tag
# per module, <folder>/v<version>. Run by .github/workflows/go.yml.
#
# Usage: publish.sh <tree> <version> <repository URL>
#
# Go module versions can never change once proxy.golang.org has fetched
# them, so existing tags are never moved: if every tag of the version
# exists with the same content, this does nothing; if any exists otherwise,
# it fails.
set -euo pipefail
tree=$(cd "$1" && pwd)
version=$2
remote=$3

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git clone -q "$remote" "$work/repo"
cd "$work/repo"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

tags=$(cd "$tree" && find . -name go.mod | sed 's|^\./||; s|/go.mod$||' | sort | sed "s|$|/v$version|")
if [ -z "$tags" ]; then
  echo "error: $tree holds no modules" >&2
  exit 1
fi

git rm -rq --ignore-unmatch .
cp -a "$tree/." .
git add -A
git commit -q --allow-empty -m "PotluckDB $version"

existing=0
for tag in $tags; do
  if git ls-remote --exit-code --tags origin "refs/tags/$tag" > /dev/null; then
    existing=$((existing + 1))
  fi
done
if [ "$existing" -gt 0 ]; then
  first=$(echo "$tags" | head -1)
  git fetch -q origin "refs/tags/$first:refs/tags/$first"
  if [ "$existing" -eq "$(echo "$tags" | wc -l)" ] && [ "$(git rev-parse "$first^{tree}")" = "$(git rev-parse "HEAD^{tree}")" ]; then
    echo "PotluckDB $version is already published, with the same content."
    exit 0
  fi
  echo "error: the repository already has tags for $version with other content; Go module versions cannot change, so publish a new version" >&2
  exit 1
fi

refs=(HEAD:refs/heads/main)
for tag in $tags; do
  git tag "$tag"
  refs+=("refs/tags/$tag")
done
git push -q origin "${refs[@]}"
echo "published $(git rev-parse HEAD) with tags:" $tags
