"""
FrappeTestCase — base class for all integration tests (Strategy B).

Copy this file to: your_app/tests/base.py

Guarantees:
- Administrator user in setUp and tearDown
- frappe.db.rollback() in tearDown (always, even if the test failed)
- insert_doc() helper that creates documents with ignore_permissions=True

Strategy A tests (pure mocks) inherit from unittest.TestCase directly —
they do not need FrappeTestCase because they do not touch the DB.
"""
import unittest
import frappe


class FrappeTestCase(unittest.TestCase):
    """
    Base class for integration tests in Frappe custom apps.

    All tests that query or write to the DB should inherit from this class.
    Tests that only use mocks (Strategy A) should use unittest.TestCase directly.
    """

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def insert_doc(self, doctype: str, **fields):
        """
        Create and insert a document with ignore_permissions=True.
        Returns the Document object.

        Usage:
            self.insert_doc("Purchase Order", supplier="Test Supplier", ...)
        """
        doc = frappe.get_doc({"doctype": doctype, **fields})
        doc.insert(ignore_permissions=True)
        return doc
