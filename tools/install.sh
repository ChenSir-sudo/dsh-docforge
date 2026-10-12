#!/bin/sh
# Install this skill into a DSH skill root.
#
#   tools/install.sh              -> ~/.dsh/skills/docforge   (user level, rank 400)
#   tools/install.sh <root>       -> <root>/docforge
#
# The bundle is the skill directory itself: DSH discovers <root>/<name>/SKILL.md
# and watches the root, so a new skill reaches a running session with no restart.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST_ROOT=${1:-"$HOME/.dsh/skills"}
DEST="$DEST_ROOT/docforge"

[ -f "$ROOT/SKILL.md" ] || { echo "no SKILL.md in $ROOT — refusing" >&2; exit 1; }
mkdir -p "$DEST_ROOT"

# rebuild from scratch so a removed file cannot linger
rm -rf "$DEST"
mkdir -p "$DEST"
cd "$ROOT"
find . -type f \
  ! -path './__pycache__/*' ! -path '*/__pycache__/*' \
  ! -name '*.pyc' ! -name '.DS_Store' \
  | while read -r f; do
      mkdir -p "$DEST/$(dirname "$f")"
      cp "$f" "$DEST/$f"
    done
chmod +x "$DEST/bin/docforge" "$DEST/tools/"*.sh 2>/dev/null || true

echo "installed -> $DEST"
echo "verify:    $DEST/bin/docforge skill-info"
