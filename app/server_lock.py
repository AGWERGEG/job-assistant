"""OS-owned directory lock: one live workbench per data directory."""
import os
from pathlib import Path

from .store import Problem


class DataDirectoryLock:
    def __init__(self, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = (directory / '.server.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if not self.file.seek(0, os.SEEK_END):
                    self.file.write(b'0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise Problem('数据目录正被另一工作台使用。请先停止旧工作台，再启动新版；不要让两个版本同时写同一份资料。', 409) from None

    def close(self):
        if self.file.closed:
            return
        if os.name == 'nt':
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()
