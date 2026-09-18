"""In-process worker lifecycle guard, shared with destructive data maintenance."""
import threading
lock=threading.RLock()
active=set()
