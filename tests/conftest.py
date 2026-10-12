"""Shared pytest fixtures.

The developer `.env` carries production-switched flags (BILLING_ENFORCE=1,
REQUIRE_TENANT_OPENROUTER_KEY=1, OPENROUTER_MANAGEMENT_KEY=…); the suite
contract is that both gates are opt-in — tests that exercise them set the
flag or patch the module attribute inside the test (test_billing_ledger.py,
test_tenant_openrouter_keys.py). Defaults run before every test so a fresh
zero-balance tenant can still generate and no suite can leak a real provider
call. Autouse fixtures, not an import-time pop: `app.py` re-reads `.env` via
load_dotenv() at import, which happens after this file loads.
"""

import os
import sys

import pytest

# Tests run from anywhere: pin the repo root on sys.path, and expose every
# folder under modules/ so `import app`/`import db` resolve regardless of the
# invocation directory or test file depth.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULES_ROOT = os.path.join(_REPO_ROOT, 'modules')
_SCRIPTS_ROOT = os.path.join(_REPO_ROOT, 'scripts')
sys.path.insert(0, _REPO_ROOT)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)
if os.path.isdir(_MODULES_ROOT):
    for _dirpath, _dirnames, _filenames in os.walk(_MODULES_ROOT):
        _dirnames.sort()
        if any(_f.endswith('.py') for _f in _filenames) and _dirpath not in sys.path:
            sys.path.insert(0, _dirpath)
    del _dirpath, _dirnames, _filenames
del _REPO_ROOT, _MODULES_ROOT


@pytest.fixture(autouse=True)
def _external_gates_default_off():
    os.environ.pop('BILLING_ENFORCE', None)
    app_module = sys.modules.get('app')
    if app_module is not None:
        app_module.REQUIRE_TENANT_OPENROUTER_KEY = False
        app_module.OPENROUTER_MANAGEMENT_KEY = None
    yield
