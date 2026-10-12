"""Path bootstrap for scripts/: running `python scripts/<tool>.py` puts only
scripts/ on sys.path, so `import app`/`import db` would fail. Importing this
module adds the repo root and every modules/<domain>/ folder to sys.path."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_MODULES_ROOT = os.path.join(_ROOT, 'modules')
if os.path.isdir(_MODULES_ROOT):
    for _dirpath, _dirnames, _filenames in os.walk(_MODULES_ROOT):
        _dirnames.sort()
        if any(_f.endswith('.py') for _f in _filenames) and _dirpath not in sys.path:
            sys.path.insert(0, _dirpath)
