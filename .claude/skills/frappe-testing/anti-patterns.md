# Anti-Patterns Found in Real Frappe Apps

Seven bugs discovered during a test audit of a production Frappe custom app.
Each one is shown with the real failure mode and the fix.

---

## AP-01 — Guard checks the wrong key in setUp

### Code with bug

```python
def _create_origin_zone(self):
    # ❌ Checks "ZONE-002" (destination) to decide whether to create "ZONE-001" (origin)
    if frappe.db.exists("Freight Zone", {"name": "ZONE-002"}):
        return
    freight_zone = frappe.get_doc({
        "doctype": "Freight Zone",
        "city": "ZONE-001",   # this is what gets inserted
        ...
    })
    freight_zone.insert()
```

### Why it breaks

1. First run (clean DB): guard fails (ZONE-002 does not exist) → inserts ZONE-001 ✅
2. If `setUp` raises before the test runs → `tearDown` does NOT execute (Python unittest contract)
3. ZONE-001 stays in DB without rollback
4. Second run: guard checks ZONE-002 (still absent) → tries to insert ZONE-001 again
5. `IntegrityError: Duplicate entry 'ZONE-001' for key 'PRIMARY'`
6. setUp fails → tearDown does not run → infinite contamination cycle

### Fix

```python
def _create_origin_zone(self):
    # ✅ Checks the SAME key it is about to insert
    if frappe.db.exists("Freight Zone", "ZONE-001"):
        return
    freight_zone = frappe.get_doc({
        "doctype": "Freight Zone",
        "city": "ZONE-001",
        ...
    })
    freight_zone.insert(ignore_permissions=True)
```

---

## AP-02 — Hardcoded `name` in child rows — duplicated value

### Code with bug

```python
freight_zone = frappe.get_doc({
    "doctype": "Freight Zone",
    "city": "ZONE-002",
    "postal_codes": [
        {"doctype": "Freight Zone Postal Code", "name": "abc111", "postal_code": "10001"},
        {"doctype": "Freight Zone Postal Code", "name": "abc222", "postal_code": "10002"},
        {"doctype": "Freight Zone Postal Code", "name": "abc333", "postal_code": "10003"},
        {"doctype": "Freight Zone Postal Code", "name": "abc333", "postal_code": "10004"},
        #                                         ^^^^^^^^^^^^^^^
        #                                         same name as the row above → IntegrityError
    ],
})
```

### Why it breaks

Frappe uses the `name` field as the primary key in child tables. Two child rows with the same `name` produce `IntegrityError: Duplicate entry 'abc333'` on insert.

### Fix

```python
freight_zone = frappe.get_doc({
    "doctype": "Freight Zone",
    "city": "ZONE-002",
    "postal_codes": [
        # ✅ No "name" field — Frappe generates a unique hash per row automatically
        {"doctype": "Freight Zone Postal Code", "postal_code": "10001"},
        {"doctype": "Freight Zone Postal Code", "postal_code": "10002"},
        {"doctype": "Freight Zone Postal Code", "postal_code": "10003"},
        {"doctype": "Freight Zone Postal Code", "postal_code": "10004"},
    ],
})
```

---

## AP-03 — Copy-pasted setUp across classes

### The problem

Two test files (`test_document_a.py` and `test_document_b.py`) had **identical setUp code** — copied word for word — including both AP-01 and AP-02. When the bugs were introduced, they were duplicated to both files. Any future fix in one file silently fails to apply to the other.

### Fix

Extract shared setup to a module of fixtures or builders:

```python
# your_app/tests/fixtures/zones.py
import frappe

def create_origin_zone():
    if frappe.db.exists("Freight Zone", "ZONE-001"):
        return
    frappe.get_doc({
        "doctype": "Freight Zone",
        "city": "ZONE-001",
        "postal_codes": [
            {"doctype": "Freight Zone Postal Code", "postal_code": "10001"},
            {"doctype": "Freight Zone Postal Code", "postal_code": "10002"},
        ],
    }).insert(ignore_permissions=True)

def create_destination_zone():
    if frappe.db.exists("Freight Zone", "ZONE-002"):
        return
    frappe.get_doc({
        "doctype": "Freight Zone",
        "city": "ZONE-002",
        "postal_codes": [
            {"doctype": "Freight Zone Postal Code", "postal_code": "20001"},
            {"doctype": "Freight Zone Postal Code", "postal_code": "20002"},
        ],
    }).insert(ignore_permissions=True)
```

```python
# test_document_a.py and test_document_b.py — both use the same module
from your_app.tests.fixtures.zones import create_origin_zone, create_destination_zone

class TestDocumentA(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        create_origin_zone()
        create_destination_zone()
```

---

## AP-04 — Tests disabled with `_test_` prefix

### Code with bug

```python
def _test_validate_normal_case(self):    # never runs
    ...

def _test_validate_credit_note(self):    # never runs
    ...

def _test_validate_amount_mismatch(self): # never runs
    ...
```

### The problem

Python `unittest` ignores methods without the `test_` prefix. The `_test_` prefix is silently ignored — there is no warning, no error, no indication in the test runner output. Coverage for these cases is completely gone without anyone noticing.

### Fix

If the test is intentionally skipped, use `@unittest.skip` with an explicit reason:

```python
@unittest.skip("TODO: needs refactor before re-enabling — see issue #123")
def test_validate_normal_case(self):
    ...
```

If the test is valid and should run, remove the leading underscore:

```python
def test_validate_normal_case(self):  # now runs
    ...
```

---

## AP-05 — `side_effect` list without order documentation

### Fragile code

```python
@patch("your_app.server.my_module.my_module.frappe.db.get_value")
def test_submit_reduces_outstanding(self, mock_get_value):
    mock_get_value.side_effect = [
        "PI-PREPAY-001",  # ← which call is this?
        1,                # ← and this?
        5000.0,           # ← and this?
        "MXN",            # ← and this?
    ]
```

If the function internally reorders, adds, or removes a call to `get_value`, the values shift and the test breaks with a confusing type or value error.

### Fix

Document the call order explicitly:

```python
mock_get_value.side_effect = [
    "PI-PREPAY-001",  # 1st call: get_value(doctype, name, "return_against")
    1,                # 2nd call: get_value(doctype, name, "is_prepayment")
    5000.0,           # 3rd call: get_value(doctype, name, "outstanding_amount")
    "MXN",            # 4th call: get_value("Company", company, "default_currency")
]
```

Or use a dict-based `side_effect` function for greater robustness:

```python
def get_value_side_effect(doctype, name, fieldname, *args, **kwargs):
    data = {
        ("Purchase Invoice", "PI-PREPAY-001", "return_against"): "PI-PREPAY-001",
        ("Purchase Invoice", "PI-PREPAY-001", "is_prepayment"): 1,
        ("Purchase Invoice", "PI-PREPAY-001", "outstanding_amount"): 5000.0,
        ("Company", "My Company", "default_currency"): "MXN",
    }
    return data.get((doctype, name, fieldname))

mock_get_value.side_effect = get_value_side_effect
```

---

## AP-06 — Order-dependent test methods within the same class

### Code with bug

```python
@classmethod
def setUpClass(cls):
    cls.workflow_done = False  # shared flag between tests

def test_workflow_step_a(self):
    # Creates the data and implicitly sets state
    self._run_step_a()
    # ... cls.workflow_done is now True

def test_workflow_step_c_rebilling(self):
    # Assumes test_a already ran
    if not self.workflow_done:
        self._run_step_a()  # fallback, but state may be inconsistent
```

Tests run in alphabetical order (`_a` before `_c`). If `_a` is skipped or fails, `_c` re-runs setup with potentially inconsistent DB state.

### Fix

Each test must be completely independent. If they share expensive setup, use an explicit `setUpClass` with no flags:

```python
@classmethod
def setUpClass(cls):
    super().setUpClass()
    frappe.set_user("Administrator")
    # Create all required state ONCE for the entire class
    cls.invoice = cls._create_test_invoice()

def test_rebilling_uses_correct_reference(self):
    # Uses cls.invoice directly — does not depend on another test
    result = process_rebilling(self.invoice.name)
    self.assertEqual(result.reference, self.invoice.name)
```

---

## AP-07 — Empty placeholder `test_*.py` files

### The pattern

```python
# See license.txt

import unittest


class TestMyFeature(unittest.TestCase):
    pass
```

### The problem

A developer sees `test_my_feature.py` exists and assumes coverage is in place. It is not. The suite reports N test files when only a fraction have real content.

### Decision

- If there are no plans to write tests for this module in the near term → **delete the file**.
- If tests need to be written → **write them now**, do not leave the placeholder.
- Never commit a `test_*.py` file with only `pass`.
