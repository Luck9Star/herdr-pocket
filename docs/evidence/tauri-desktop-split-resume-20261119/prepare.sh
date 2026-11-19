#!/bin/sh
set -eu
repo=$1
ref=$2
build=$3
scope=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
dependencies=${HERDR_D2_NODE_MODULES:-"$repo/validation/tauri/node_modules"}
test -d "$dependencies"
test ! -e "$build"
mkdir "$build"
build=$(CDPATH='' cd -- "$build" && pwd)
commit=$(git -C "$repo" rev-parse "$ref^{commit}")
git -C "$repo" archive "$commit" validation/tauri validation/shared   validation/vendor/RUSSH-NOTICE.md validation/vendor/russh-0.65.0-source.json   validation/vendor/russh-0.65.0-local-close.patch validation/vendor/russh-0.65.0-LICENSE-APACHE |
  tar -x -C "$build"
ln -s "$dependencies" "$build/validation/tauri/node_modules"
cp "$scope/browser-probe.mjs" "$build/browser-probe.mjs"
printf '%s\n' "$commit" > "$build/SOURCE_COMMIT"
(
  cd "$build/validation/tauri"
  node scripts/prepare-fixtures.mjs
  node node_modules/vite/bin/vite.js build --configLoader runner --outDir "$build/site" --emptyOutDir
)
