"""Optional Portal mode lease. Missing/stale state suppresses OS actions."""
import json
import os
from pathlib import Path
import time


def snapshot(path, now=None):
    if not path:
        return {'os_mode': True, 'mapper_allowed': True}
    try:
        p = Path(path)
        stat = p.stat()
        if p.is_symlink() or stat.st_uid != os.getuid():
            return {}
        state = json.loads(p.read_text())
        age = (time.monotonic() if now is None else now) - state['updated']
        return state if 0 <= age < 2 else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def allowed(path, now=None):
    return snapshot(path, now).get('mapper_allowed') is True
