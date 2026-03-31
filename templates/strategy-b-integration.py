"""
Strategy B — Integration test with real DB + rollback.

Use when the function under test runs queries or inserts real records.
Inherits from FrappeTestCase (see templates/base-test-class.py), which
guarantees Administrator user and frappe.db.rollback() in every tearDown.

Requires a dedicated test site — never run against the dev site.

Run:
    bench --site your-test-site.localhost run-tests --skip-test-records \
      --module your_app.server.my_module.test_my_module
"""
import unittest
import frappe

from your_app.tests.base import FrappeTestCase
from your_app.tests.builders.supplier_builder import create_supplier
from your_app.tests.builders.item_builder import create_item


class TestMyDocType(FrappeTestCase):
    """
    Tests for MyDocType validation logic.
    setUp creates the minimum required data via builders.
    tearDown (inherited from FrappeTestCase) rolls back all DB changes.
    """

    def setUp(self):
        super().setUp()
        self._create_test_data()

    # ─── Setup helpers ────────────────────────────────────────────────────────

    def _create_test_data(self):
        self.supplier_name = create_supplier()
        self.item_code = create_item()
        self._create_main_doc()

    def _create_main_doc(self):
        # RULE: the guard ALWAYS checks the same key it is about to insert.
        if frappe.db.exists("My DocType", "TEST-DOC-001"):
            self.test_doc = frappe.get_doc("My DocType", "TEST-DOC-001")
            return

        self.test_doc = self.insert_doc(
            "My DocType",
            name="TEST-DOC-001",
            supplier=self.supplier_name,
            item_code=self.item_code,
            amount=1000.0,
        )

    # ─── Tests ────────────────────────────────────────────────────────────────

    def test_validate_passes_with_valid_data(self):
        self.test_doc.reload()
        self.test_doc.validate()  # must not raise

    def test_validate_raises_with_invalid_state(self):
        self.test_doc.some_field = "invalid-value"
        with self.assertRaises(frappe.ValidationError):
            self.test_doc.validate()

    def test_correct_amount_after_processing(self):
        self.test_doc.reload()
        result = process_my_doc(self.test_doc.name)

        self.assertEqual(result.status, "Processed")
        self.assertEqual(result.final_amount, 1000.0)


# ─── Notes ────────────────────────────────────────────────────────────────────
#
# Builder rules:
#   1. create_supplier(), create_item(), etc. are idempotent — safe to call in
#      every setUp without Duplicate Entry errors.
#   2. Builders accept **overrides when you need specific values:
#        create_supplier(supplier_name="Specific Vendor Ltd")
#   3. Builders never call frappe.db.commit() — tearDown rollback cleans them up.
#
# Child rows:
#   Never hardcode the "name" field in child rows. Frappe generates it automatically.
#   Setting it manually causes IntegrityError when two rows share the same name.
#
# DO NOT set "name" on child rows:
#   ❌  {"doctype": "My Child", "name": "abc123", "field": "value"}
#   ✅  {"doctype": "My Child", "field": "value"}
