#!/bin/zsh
set -u
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1
PYTHON_BIN=""
if [[ -d "$SCRIPT_DIR/runtime" ]]; then
  if ! [[ -x "$SCRIPT_DIR/runtime/bin/python3" ]] || ! "$SCRIPT_DIR/runtime/bin/python3" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    echo "包内运行时无法启动。请核对来源和系统拦截提示，或重新解压已核验的便携包。"
    exit 1
  fi
  PYTHON_BIN="$SCRIPT_DIR/runtime/bin/python3"
fi
for candidate in "$SCRIPT_DIR/runtime/bin/python3" "$SCRIPT_DIR/.venv/bin/python" "$(command -v python3)" "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
  [[ -n "$PYTHON_BIN" ]] && break
  [[ "$candidate" == /usr/bin/python3 ]] && ! /usr/bin/xcode-select -p >/dev/null 2>&1 && continue
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "没有找到 Python 3.10+。请使用 macOS 便携版，或先安装 Python 3.10+。"
  read -k 1 "?按任意键关闭..."
  exit 1
fi
exec "$PYTHON_BIN" launch.py --demo
