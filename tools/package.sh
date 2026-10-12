#!/bin/sh
# Build the distributable zip. The bundle is the skill directory itself:
# drop it into any skill root as <root>/docforge/ and it works.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAME=$(basename "$ROOT")
OUT=${1:-"$ROOT/../$NAME-skill.zip"}
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$NAME"
cd "$ROOT"
find . -type f \
  ! -path './__pycache__/*' ! -path '*/__pycache__/*' \
  ! -name '*.pyc' ! -name '.DS_Store' \
  | while read -r f; do
      mkdir -p "$STAGE/$NAME/$(dirname "$f")"
      cp "$f" "$STAGE/$NAME/$f"
    done

( cd "$STAGE" && zip -qr "$OUT" "$NAME" )
echo "wrote $OUT"
unzip -l "$OUT" | tail -3
