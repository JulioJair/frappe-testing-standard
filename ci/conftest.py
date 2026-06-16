"""
pytest conftest for Strategy A (mock-based) unit tests.

Sets up a minimal frappe environment without a real DB connection so that
tests using @patch on frappe.db.* can run in CI without a full bench setup.

HOW TO USE:
  1. Copy this file to your app root (same directory as setup.py / pyproject.toml).
  2. Replace MOCKED_PACKAGES with any private/heavy app dependencies that
     should not be imported in CI (e.g. erpnext, your_private_dependency).
  3. Run your Strategy A tests with:
       python -m pytest $(cat .github/unit-tests.txt | grep -v '#') -v

WHAT THIS DOES:
  - Intercepts imports of MOCKED_PACKAGES and returns MagicMock objects,
    so tests can import modules that depend on them without installing them.
  - Creates a temp site directory and calls frappe.init() without a real DB.
  - Sets frappe.local.session so frappe.session.user resolves correctly.
  - Replaces frappe.db with a MagicMock — all frappe.db.* calls return mocks
    unless a test patches them with @patch.
  - Patches frappe internals that would recurse into DB on Document creation.

WHAT YOUR TESTS MUST NOT DO (because this conftest.py already does it):
  - frappe.init() / frappe.destroy() in setUp/tearDown
  - frappe.set_user() in setUp/tearDown
  - frappe.local.db = MagicMock() in setUpClass

IMPORTANT: frappe.db is set as a module attribute (frappe.db = MagicMock()),
not as frappe.local.db. This means @patch("frappe.db.get_value") patches the
module attribute — which is what Strategy A tests use. Strategy B tests that
call frappe.db.rollback() directly still work because they run under bench,
not under pytest.
"""
import importlib
import json
import logging
import os
import sys
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# ✏️  CUSTOMIZE: list any packages that should not be imported in CI.
# Submodule imports (e.g. "from erpnext.accounts import X") are also mocked.
# ---------------------------------------------------------------------------
_MOCKED_PACKAGES = {
    "erpnext",
    # "your_other_private_dependency",
}


# ---------------------------------------------------------------------------
# Meta path finder — intercepts _MOCKED_PACKAGES and their submodules.
# Uses the modern find_spec/create_module API (Python 3.4+) with
# is_package=True so Python treats every mocked module as a package.
# ---------------------------------------------------------------------------
class _PackageMocker(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in _MOCKED_PACKAGES:
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        if spec.name in sys.modules:
            return sys.modules[spec.name]
        mock = MagicMock()
        mock.__name__ = spec.name
        mock.__package__ = spec.name
        mock.__spec__ = spec
        mock.__path__ = []
        mock.__file__ = None
        mock.__loader__ = self
        sys.modules[spec.name] = mock
        return mock

    def exec_module(self, module):
        pass  # MagicMock attributes accessible via __getattr__


sys.meta_path.insert(0, _PackageMocker())

# ---------------------------------------------------------------------------
# Minimal frappe site setup — no DB connection required.
# ---------------------------------------------------------------------------
_SITES_PATH = "/tmp/frappe_ci_sites"
_SITE = "test.localhost"
_SITE_DIR = os.path.join(_SITES_PATH, _SITE)
os.makedirs(_SITE_DIR, exist_ok=True)

with open(os.path.join(_SITE_DIR, "site_config.json"), "w") as _f:
    json.dump({"db_name": "_test", "db_password": "test"}, _f)

with open(os.path.join(_SITES_PATH, "apps.txt"), "w") as _f:
    _f.write("frappe\n")

import frappe  # noqa: E402 — must come after meta path finder is registered

frappe.init(site=_SITE, sites_path=_SITES_PATH)
frappe.local.session = frappe._dict(user="Administrator")

# Replace frappe.db on the module — this is what @patch("frappe.db.get_value") targets.
frappe.db = MagicMock()

if not hasattr(frappe.local, "valid_columns"):
    frappe.local.valid_columns = {}
if not hasattr(frappe.local, "flags"):
    frappe.local.flags = frappe._dict()

# ---------------------------------------------------------------------------
# Patch frappe.get_meta to break the Meta → Document → meta → get_meta
# recursion that occurs when frappe.get_doc({...}) is called in tests.
# ---------------------------------------------------------------------------
frappe.get_meta = lambda doctype, cached=True: MagicMock()

# ---------------------------------------------------------------------------
# Patch get_controller to avoid DB lookup for unknown doctypes.
#
# frappe.model.base_document._get_controller() calls frappe.db.get_value()
# and unpacks the result. Since frappe.db is a MagicMock, iteration fails.
#
# Strategy: try to import the real controller for doctypes in your app;
# fall back to the base Document class for everything else.
# ---------------------------------------------------------------------------
import frappe.model.base_document as _frappe_base_doc  # noqa: E402
import frappe.model.document as _frappe_doc            # noqa: E402
from frappe.model.document import Document as _FrappeDoc  # noqa: E402
from frappe.model.base_document import BaseDocument as _FrappeBase  # noqa: E402


def _mock_get_controller(doctype):
    # ✏️  CUSTOMIZE: replace "your_app" with your app name.
    try:
        _scrubbed = frappe.scrub(str(doctype))
        _mod = importlib.import_module(f"your_app.your_app.doctype.{_scrubbed}.{_scrubbed}")
        _cls = str(doctype).replace(" ", "").replace("-", "")
        if hasattr(_mod, _cls):
            return getattr(_mod, _cls)
    except Exception:
        pass
    return _FrappeDoc


def _mock_init_child(self, value, key):
    return frappe._dict(value)


_frappe_base_doc.get_controller = _mock_get_controller
_frappe_doc.get_controller = _mock_get_controller
_FrappeBase._init_child = _mock_init_child
_FrappeBase.get_valid_columns = lambda self: []

# ---------------------------------------------------------------------------
# Patch frappe.get_doc to preserve underscore-prefixed keys (like
# _doc_before_save) that frappe.Document.update() silently drops.
# ---------------------------------------------------------------------------
_real_get_doc = frappe.get_doc


def _patched_get_doc(d_or_doctype, *args, **kwargs):
    _extras = {}
    if isinstance(d_or_doctype, dict):
        d_or_doctype = dict(d_or_doctype)
        for _k in list(d_or_doctype.keys()):
            if _k.startswith("_"):
                _extras[_k] = d_or_doctype.pop(_k)
    _doc = _real_get_doc(d_or_doctype, *args, **kwargs)
    for _k, _v in _extras.items():
        _doc.__dict__[_k] = _v
    return _doc


frappe.get_doc = _patched_get_doc

# Frappe v13: utils.logger may be missing get_logger_stderr.
try:
    import frappe.utils.logger as _logger
    if not hasattr(_logger, "get_logger_stderr"):
        _logger.get_logger_stderr = lambda name: logging.getLogger(name)
except (ImportError, AttributeError):
    pass
