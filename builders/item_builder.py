"""
Item builder — idempotent factory for test Item records.

Copy to: your_app/tests/builders/item_builder.py
"""
import frappe


def create_item(**overrides) -> str:
    """
    Create a test Item. Idempotent: returns the item_code if it already exists.

    Returns: the Item name / item_code (str).

    Usage:
        item = create_item()
        item = create_item(item_code="RAW-MAT-001", item_name="Raw Material", is_stock_item=1)
    """
    defaults = {
        "item_code": "TEST-ITEM-001",
        "item_name": "Test Item",
        "item_group": "All Item Groups",
        "stock_uom": "Nos",
        "is_stock_item": 0,
    }
    data = {**defaults, **overrides}
    name = data["item_code"]

    if frappe.db.exists("Item", name):
        return name

    frappe.get_doc({"doctype": "Item", **data}).insert(ignore_permissions=True)
    return name
