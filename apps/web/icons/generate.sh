#!/usr/bin/env bash
# Regenerates the raster icons in public/ from the two SVG sources:
#   public/favicon.svg     browser tabs (transparent, light/dark aware)
#   icons/app-icon.svg     home screens and the web manifest (opaque purple tile)
# Needs rsvg-convert (librsvg) and ImageMagick. Run: bash apps/web/icons/generate.sh
set -euo pipefail
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for size in 16 32 48; do
  rsvg-convert -w "$size" -h "$size" public/favicon.svg -o "$work/favicon-$size.png"
done
magick "$work/favicon-16.png" "$work/favicon-32.png" "$work/favicon-48.png" public/favicon.ico

rsvg-convert -w 180 -h 180 icons/app-icon.svg -o public/apple-touch-icon.png
rsvg-convert -w 192 -h 192 icons/app-icon.svg -o public/icon-192.png
rsvg-convert -w 512 -h 512 icons/app-icon.svg -o public/icon-512.png
