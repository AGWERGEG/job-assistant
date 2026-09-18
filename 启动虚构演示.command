#!/bin/zsh
set -u
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1
PYTHON_BIN=""
for candidate in "$SCRIPT_DIR/.venv/bin/python" "$(command -v python3)" "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "没有找到 Python 3.10+。请先安装或在 .venv 中配置。"
  read -k 1 "?按任意键关闭..."
  exit 1
fi
exec "$PYTHON_BIN" launch.py --demo
