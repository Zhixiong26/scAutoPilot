"""Shared serialization and locks for immutable review rounds and config updates."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re

from _common import load_structured


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('%s must be a path-safe identifier' % label)
    return value


def mapping(path):
    value = load_structured(Path(path))
    if not isinstance(value, dict):
        raise ValueError('expected a mapping in %s' % path)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextmanager
def exclusive_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another optimization operation owns %s' % path) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
