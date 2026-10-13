#!/bin/sh
# Golden-image regression for the shipped figures.
#
# The validator proves the geometry is sound. Nothing proved that the figures
# still *look* right -- so a stylesheet change could break every one of them and
# the whole suite would stay green. That happened twice: a figure role styled in
# the standalone export but not in the page, and a funnel silently drawn as a
# rectangle.
#
# Opt-in on purpose: it needs a browser, and a missing or busy browser must not
# turn the normal suite red.
#
#   sh tools/golden.sh           compare against the recorded baselines
#   sh tools/golden.sh --update  record the current renders as the baseline
set -e
cd "$(dirname "$0")/.."
PY="${DOCFORGE_PYTHON:-python3}"
DIR="tests/golden"
MODE="${1:-compare}"

mkdir -p "$DIR"
failed=0
count=0
skipped=0
browser_ever_worked=0
# Every figure is checked in both modes: the palettes are separate token sets,
# so a light-mode figure can be perfect while its dark twin is unreadable.
for spec in examples/engines/*.json examples/nested-figure.json; do
    base=$(basename "$spec" .json)
    for mode in light dark; do
        case "$mode" in light) name="$base" ;; *) name="$base-dark" ;; esac
        out="$DIR/$name.png"
        if [ "$MODE" = "--update" ]; then
            "$PY" -m docforge.cli fig "$spec" --mode "$mode" --png "$out" \
                --width 900 --scale 1 --no-check >/dev/null 2>&1 || {
                echo "  skip  $name (no browser?)"; skipped=$((skipped + 1)); continue; }
            echo "  wrote $out"
        else
            [ -f "$out" ] || { echo "  MISSING baseline: $out"; failed=1; continue; }
            tmp=$(mktemp -t docforge-golden).png
            if ! "$PY" -m docforge.cli fig "$spec" --mode "$mode" --png "$tmp" \
                    --width 900 --scale 1 --no-check >/dev/null 2>&1; then
                echo "  SKIP  $name (browser unavailable or busy)"
                skipped=$((skipped + 1)); rm -f "$tmp"; continue
            fi
            count=$((count + 1)); browser_ever_worked=1
            if ! "$PY" tools/compare_png.py "$out" "$tmp"; then
                echo "  DIFF  $name"
                failed=1
            else
                echo "  ok    $name"
            fi
            rm -f "$tmp"
        fi
    done
done
[ "$MODE" = "--update" ] && { echo "baselines recorded in $DIR"; exit 0; }
if [ "$count" -eq 0 ]; then
    echo "golden: NOT VERIFIED -- no figure could be rendered (no browser, or none recorded)"
    exit 0
fi
if [ "$skipped" -gt 0 ]; then
    # Partial coverage must never read as a pass: a skipped figure is one whose
    # appearance was not checked, and quietly counting it as fine is how a
    # regression test stops being one.
    echo "golden: INCOMPLETE -- $count compared, $skipped skipped; rerun when the browser is free"
    [ "$browser_ever_worked" -eq 1 ] && exit 1 || exit 0
fi
[ "$failed" -eq 0 ] && echo "golden: $count figures match" || { echo "golden: drift detected"; exit 1; }
