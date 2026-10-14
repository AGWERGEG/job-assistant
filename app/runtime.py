"""In-process worker lifecycle guard, shared with destructive data maintenance."""
import threading
import shutil
from pathlib import Path
lock=threading.RLock()
active=set()


def find_codex(explicit=None):
    candidates = (explicit, shutil.which('codex'),
                  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                  '/Applications/ChatGPT.app/Contents/Resources/codex')
    return next((str(Path(path)) for path in candidates if path and Path(path).is_file()), None)
