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


@pytest.fixture(autouse=True)
def _external_gates_default_off():
    os.environ.pop('BILLING_ENFORCE', None)
    app_module = sys.modules.get('app')
    if app_module is not None:
        app_module.REQUIRE_TENANT_OPENROUTER_KEY = False
        app_module.OPENROUTER_MANAGEMENT_KEY = None
    yield
