"""
Company builder — idempotent factory for test Company records.

Copy to: your_app/tests/builders/company_builder.py

Adjust defaults for your app (company name, abbreviation, currency, country).
"""
import frappe


def create_company(**overrides) -> str:
    """
    Create a test Company. Idempotent: returns the name if it already exists.

    Returns: the Company name (str).

    Usage:
        company = create_company()
        company = create_company(company_name="My Test Co", default_currency="USD")
    """
    defaults = {
        "company_name": "Test Company",
        "abbr": "TC",
        "default_currency": "USD",
        "country": "United States",
    }
    data = {**defaults, **overrides}
    name = data["company_name"]

    if frappe.db.exists("Company", name):
        return name

    frappe.get_doc({"doctype": "Company", **data}).insert(ignore_permissions=True)
    return name
