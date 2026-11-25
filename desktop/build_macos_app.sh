#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/tmp/gmapscrap-macos-build-venv/bin/python}"
ICON_PNG="$ROOT_DIR/desktop/assets/gmapscrap-favicon.png"
ICON_ICNS="$ROOT_DIR/desktop/assets/gmapscrap.icns"
ICONSET_DIR="${TMPDIR:-/tmp}/gmapscrap.iconset"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/desktop/dist}"
BUILD_WORK_DIR="${BUILD_WORK_DIR:-$ROOT_DIR/desktop/build}"
BUILD_SPEC_DIR="${BUILD_SPEC_DIR:-$ROOT_DIR/desktop/build}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python build environment not found: $PYTHON_BIN" >&2
  echo "Create it and install desktop/requirements.txt plus pyinstaller first." >&2
  exit 1
fi

if [ ! -f "$ICON_ICNS" ] || [ "$ICON_PNG" -nt "$ICON_ICNS" ] || [ "${REGENERATE_ICON:-0}" = "1" ]; then
  rm -r "$ICONSET_DIR" 2>/dev/null || true
  mkdir -p "$ICONSET_DIR"
  for size in 16 32 64 128 256 512; do
    sips -z "$size" "$size" "$ICON_PNG" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
    double_size=$((size * 2))
    sips -z "$double_size" "$double_size" "$ICON_PNG" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"
fi

mkdir -p "$BUILD_SPEC_DIR"
"$PYTHON_BIN" - "$ROOT_DIR" "$BUILD_SPEC_DIR/build-info.json" <<'PY'
import hashlib
import importlib.metadata
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

root = Path(sys.argv[1])
paths = sorted([*root.glob('desktop/*.py'), *root.glob('desktop/assets/*'),
                *root.glob('backend/scrapers/*.py'), root/'backend/config.py',
                root/'backend/services/text_normalization.py', root/'backend/services/email_validation.py',
                root/'backend/services/phone_region.py', root/'desktop/requirements.txt'])
sources = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
           for path in paths if path.is_file()}
metadata = {
    'built_at': datetime.now(ZoneInfo('America/Fortaleza')).isoformat(),
    'git_commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
    'source_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
    'source_files': sources,
    'python': sys.version,
    'dependencies': {name: importlib.metadata.version(name) for name in ('PyInstaller', 'PySide6', 'selenium', 'psutil')},
}
Path(sys.argv[2]).write_text(json.dumps(metadata, indent=2) + '\n')
PY

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name GmapScrap \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier br.com.automasoluct.gmapscrap \
  --add-data "$ROOT_DIR/desktop/assets:assets" \
  --add-data "$BUILD_SPEC_DIR/build-info.json:." \
  --collect-submodules selenium.webdriver \
  --collect-data selenium \
  --collect-binaries selenium \
  --paths "$ROOT_DIR" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_WORK_DIR" \
  --specpath "$BUILD_SPEC_DIR" \
  "$ROOT_DIR/desktop/app.py"

echo "$DIST_DIR/GmapScrap.app"
