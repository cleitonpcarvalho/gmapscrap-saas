#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/tmp/gmapscrap-macos-build-venv/bin/python}"
ICON_PNG="$ROOT_DIR/desktop/assets/gmapscrap-favicon.png"
ICON_ICNS="$ROOT_DIR/desktop/assets/gmapscrap.icns"
ICONSET_DIR="${TMPDIR:-/tmp}/gmapscrap.iconset"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python build environment not found: $PYTHON_BIN" >&2
  echo "Create it and install desktop/requirements.txt plus pyinstaller first." >&2
  exit 1
fi

rm -r "$ICONSET_DIR" 2>/dev/null || true
mkdir -p "$ICONSET_DIR"

for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
  double_size=$((size * 2))
  sips -z "$double_size" "$double_size" "$ICON_PNG" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name GmapScrap \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier br.com.automasoluct.gmapscrap \
  --add-data "$ROOT_DIR/desktop/assets:assets" \
  --paths "$ROOT_DIR" \
  --distpath "$ROOT_DIR/desktop/dist" \
  --workpath "$ROOT_DIR/desktop/build" \
  --specpath "$ROOT_DIR/desktop/build" \
  "$ROOT_DIR/desktop/app.py"

echo "$ROOT_DIR/desktop/dist/GmapScrap.app"
