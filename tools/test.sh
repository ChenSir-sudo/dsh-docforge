#!/bin/sh
# Run the whole suite on every interpreter we can find.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

run() {
  echo "== $1"
  "$1" -m unittest discover -s tests -t . "$@" 2>/dev/null || "$1" -m unittest discover -s tests -t .
}

PRIMARY=${DOCFORGE_PYTHON:-python3}
echo "== $PRIMARY  ($($PRIMARY -V 2>&1))"
"$PRIMARY" -m unittest discover -s tests -t . -v

if [ -x /usr/bin/python3 ] && [ "$(command -v python3)" != "/usr/bin/python3" ]; then
  echo
  echo "== /usr/bin/python3  ($(/usr/bin/python3 -V 2>&1))  — 3.9 compatibility check"
  /usr/bin/python3 -m unittest discover -s tests -t .
fi

echo
echo "== end-to-end on the shipped examples"
for ex in examples/*/material.md; do
  [ -e "$ex" ] || continue
  echo "-- $ex"
  "$PRIMARY" -m docforge.cli check "$ex"
  "$PRIMARY" -m docforge.cli build "$ex" -o /tmp/docforge-e2e.html
done
