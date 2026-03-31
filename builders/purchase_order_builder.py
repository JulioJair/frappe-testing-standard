"""
Purchase Order builder — idempotent factory for test Purchase Order records.

Copy to: your_app/tests/builders/purchase_order_builder.py

Note: Purchase Orders are auto-named by Frappe (naming series like PO-YYYY-NNNNN),
so this builder does NOT check for existence by name. It always creates a new PO.
Use sparingly — each call inserts a new record that tearDown must roll back.
"""
import frappe

from your_app.tests.builders.supplier_builder import create_supplier
from your_app.tests.builders.item_builder import create_item


def create_purchase_order(**overrides) -> str:
    """
    Create a Purchase Order in Draft state.
    Returns: the Purchase Order name (str).

    Usage:
        po = create_purchase_order()
        po = create_purchase_order(supplier="Specific Vendor Ltd", qty=5, rate=200.0)
    """
    supplier = overrides.pop("supplier", None) or create_supplier()
    item_code = overrides.pop("item_code", None) or create_item()
    qty = overrides.pop("qty", 1)
    rate = overrides.pop("rate", 1000.0)

    defaults = {
        "supplier": supplier,
        "schedule_date": frappe.utils.today(),
        "items": [
            {
                "doctype": "Purchase Order Item",
                "item_code": item_code,
                "qty": qty,
                "rate": rate,
                "schedule_date": frappe.utils.today(),
            }
        ],
    }
    data = {**defaults, **overrides}

    doc = frappe.get_doc({"doctype": "Purchase Order", **data})
    doc.insert(ignore_permissions=True)
    return doc.name
