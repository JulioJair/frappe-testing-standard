"""
Supplier builder — idempotent factory for test Supplier records.

Copy to: your_app/tests/builders/supplier_builder.py
"""
import frappe


def create_supplier(**overrides) -> str:
    """
    Create a test Supplier. Idempotent: returns the name if it already exists.

    Returns: the Supplier name (str).

    Usage:
        supplier = create_supplier()
        supplier = create_supplier(supplier_name="Specific Vendor Ltd", country="Mexico")
    """
    defaults = {
        "supplier_name": "Test Supplier",
        "supplier_group": "All Supplier Groups",
        "supplier_type": "Company",
        "country": "United States",
    }
    data = {**defaults, **overrides}
    name = data["supplier_name"]

    if frappe.db.exists("Supplier", name):
        return name

    frappe.get_doc({"doctype": "Supplier", **data}).insert(ignore_permissions=True)
    return name
