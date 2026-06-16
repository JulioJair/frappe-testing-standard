"""
Strategy A — Unit test with mocks.

Use when the function under test does not touch the DB.
All frappe.db calls are replaced with unittest.mock.patch.

This test runs without bench and without a database — suitable for CI.

CI context (conftest.py):
  Strategy A tests run under pytest in CI. The repo's conftest.py handles
  frappe initialization at the session level — it calls frappe.init(), sets
  frappe.local.session, and replaces frappe.db with a MagicMock. Because of
  this, Strategy A test classes must NOT define setUp/tearDown that call
  frappe.init(), frappe.destroy(), or frappe.set_user() — those are dead code
  under both pytest (conftest.py runs first) and bench (frappe.local is already
  initialized). Define setUp/tearDown only when the test itself needs per-test
  state (e.g. building a shared MagicMock document).
"""
import unittest
from unittest.mock import patch, MagicMock
import frappe


class TestMyFunction(unittest.TestCase):

    # ─── Happy path ───────────────────────────────────────────────────────────

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    @patch("your_app.server.my_module.my_module.frappe.db.set_value")
    def test_happy_path(self, mock_set, mock_get):
        # @patch decorators are injected in REVERSE order (last decorator = first param).
        # mock_set → frappe.db.set_value
        # mock_get → frappe.db.get_value

        # Arrange: side_effect in the same order the function calls them.
        mock_get.side_effect = [
            "LINKED-DOC-001",  # 1st call: get_value(doctype, name, "linked_field")
            1000.0,            # 2nd call: get_value(doctype, name, "amount")
        ]

        doc = MagicMock()
        doc.name = "TEST-DOC-001"
        doc.grand_total = 500.0

        # Act
        from your_app.server.my_module.my_module import my_function
        my_function(doc)

        # Assert
        mock_set.assert_called_once_with(
            "My DocType", "LINKED-DOC-001", "field_name", 500.0
        )

    # ─── Edge cases ───────────────────────────────────────────────────────────

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    def test_early_return_when_linked_doc_not_found(self, mock_get):
        mock_get.return_value = None
        doc = MagicMock()

        from your_app.server.my_module.my_module import my_function
        my_function(doc)

        # Function returned early — get_value was called exactly once and nothing else happened
        mock_get.assert_called_once()

    # ─── Error conditions ─────────────────────────────────────────────────────

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    def test_raises_validation_error_on_invalid_state(self, mock_get):
        mock_get.return_value = "invalid-state"
        doc = MagicMock()
        doc.name = "TEST-DOC-001"

        from your_app.server.my_module.my_module import my_function
        with self.assertRaises(frappe.ValidationError):
            my_function(doc)
