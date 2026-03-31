# Decision Tree — Which Strategy to Use?

---

## The rule

```
What does the function under test do?
│
├─► Pure logic only (calculations, transformations, in-memory validations)
│   └─► STRATEGY A — Unit test with mocks
│       Examples: date calculations, tax computations, string formatters,
│                 field validators that only read from the doc object
│
├─► Queries or writes to DB (frappe.db.get_value, frappe.get_doc, .insert)
│   └─► STRATEGY B — Integration test with real DB + rollback
│       Examples: document validation that fetches linked records,
│                 functions that insert or update DB state
│
├─► Full end-to-end flow (external APIs, background jobs, PDF/XML, multi-doc)
│   └─► STRATEGY C — Conditional test with @skipUnless
│       Examples: e-invoice submission to a tax authority,
│                 payment gateway integration, background job chains
│
└─► test_*.py file exists but is empty (placeholder)
    └─► Evaluate if the functionality deserves tests.
        If yes, choose A or B above. If not, delete the file.
```

---

## Strategy A — Unit test with mocks

**When:** the function does not touch the DB. All external dependencies can be mocked.

**Where the tests run:** anywhere — `pytest` or `bench run-tests`. No DB required.

See template: `templates/strategy-a-unit.py`

### Critical rules

- The path in `@patch` must be **where the name is used**, not where it is defined.
  - ✅ `@patch("your_app.server.my_module.my_module.frappe.db.get_value")`
  - ❌ `@patch("frappe.db.get_value")` — patches the original, not the local import
- `@patch` parameters are injected in **reverse** order of decorators (last decorator = first parameter).
- When using `side_effect` with a list, document the call order with inline comments. If the internal function reorders its calls, the test breaks silently otherwise.
- Do not call `frappe.db.rollback()` in `tearDown` — there is nothing to clean up.
- **If a mock assertion is your only way to verify correctness, the function needs refactoring.** `assert_called_once_with(set_value, ...)` tests *how* the function works, not *what* it produces. Extract the calculation into a pure function and assert on its return value instead:

  ```python
  # ❌ Tests implementation — breaks on any internal refactor
  mock_set.assert_called_once_with("Purchase Invoice", name, "field", 300.0)

  # ✅ Tests behavior — extract the logic and assert the result directly
  result = _calculate_new_prepayment_amount(current=500.0, credit_note=200.0, is_reversal=False)
  self.assertEqual(result, 300.0)
  ```

  The need for a mock assertion is a signal, not a solution.
- If the function under test calls `frappe.db.commit()` explicitly, mock it — an un-mocked commit persists data that a later `rollback()` cannot undo:
  ```python
  @patch("your_app.server.my_module.my_module.frappe.db.commit")
  def test_something(self, mock_commit):
      my_function(doc)
  ```

### frappe.flags.in_test

`bench run-tests` sets `frappe.flags.in_test = True` automatically. Use this flag in **production code** to skip expensive side effects during test runs:

```python
def submit_to_tax_authority(doc):
    if frappe.flags.in_test:
        return  # skip external API call in test context
    # ... real submission logic
```

Useful for: email sending, external API calls, PDF/XML generation, background job enqueueing.

> **Important:** This is not a substitute for mocking. If the function has logic worth testing, use `@patch` to mock the dependency and verify the logic. `frappe.flags.in_test` is for side effects you want to suppress globally, not for making untestable code testable.

---

## Strategy B — Integration test with real DB

**When:** the function queries or writes to the DB. Mocking it would test the mock, not the function.

**Where the tests run:** against a dedicated test site — never the dev site.

```bash
# Always against the test site
bench --site your-test-site.localhost run-tests --skip-test-records --app your_app

# Single module
bench --site your-test-site.localhost run-tests --skip-test-records \
  --module your_app.server.my_module.test_my_module
```

> ⚠️ **Never run against your dev site.** It contaminates development data and causes
> `Duplicate Entry` errors on subsequent runs.

See template: `templates/strategy-b-integration.py`

### Critical rules

**1. The guard checks the SAME key it inserts**

```python
# ✅ CORRECT
def _create_test_zone(self):
    if frappe.db.exists("Freight Zone", "ZONE-001"):   # same key
        return
    frappe.get_doc({"city": "ZONE-001", ...}).insert()

# ❌ WRONG — the most common bug in Frappe test suites
def _create_test_zone(self):
    if frappe.db.exists("Freight Zone", {"name": "ZONE-002"}):  # DIFFERENT key
        return
    frappe.get_doc({"city": "ZONE-001", ...}).insert()  # inserts ZONE-001 → Duplicate Entry
```

**2. Never hardcode `name` in child rows**

```python
# ✅ CORRECT — Frappe generates child names automatically
"items": [
    {"doctype": "Purchase Order Item", "item_code": "TEST-ITEM-001", "qty": 1},
    {"doctype": "Purchase Order Item", "item_code": "TEST-ITEM-002", "qty": 2},
]

# ❌ WRONG — two rows with the same name → IntegrityError
"items": [
    {"doctype": "Purchase Order Item", "name": "abc123", "item_code": "TEST-ITEM-001"},
    {"doctype": "Purchase Order Item", "name": "abc123", "item_code": "TEST-ITEM-002"},
]
```

**3. If setUp can fail, tearDown does not run → double contamination**

The vicious cycle:
```
setUp fails (Duplicate Entry)
  → tearDown does NOT run (Python unittest contract)
  → record stays in DB
  → next setUp also fails (same Duplicate Entry)
  → all tests in the class fail permanently on that DB
```

Fix: correct guards + a clean test site restored from backup.

**4. `frappe.db.rollback()` in tearDown only undoes uncommitted changes**

If `.insert()` was committed during setUp (by an implicit flush), the `tearDown` rollback will not undo it. Keep your test site clean — restore from backup when the state is corrupted.

---

## Strategy C — Conditional test with @skipUnless

**When:** the test requires an external service, background worker, or multi-doc flow
that cannot be meaningfully mocked without rewriting the function under test.

```python
import os
import unittest

RUN_INTEGRATION_TESTS = bool(os.environ.get("RUN_INTEGRATION_TESTS"))


class TestExternalWorkflow(unittest.TestCase):

    @unittest.skipUnless(RUN_INTEGRATION_TESTS, "Requires external service: RUN_INTEGRATION_TESTS=1")
    def test_end_to_end_submission(self):
        ...
```

These tests never run in standard `bench run-tests`. They require:

```bash
RUN_INTEGRATION_TESTS=1 bench --site your-test-site.localhost run-tests \
  --module your_app.server.my_module.test_my_module
```

---

## What to test — business rules, not framework behavior

### Test ONLY this

- **Business rules:** validations, calculations, decisions, domain-specific transformations
- **Domain invariants:** "a credit note can never take the balance below zero"
- **Function contracts:** "given this input, returns this output / raises this error"

### Never test this

| ❌ Do not test | Why |
|---|---|
| `frappe.db.insert()` works | That is the framework's responsibility |
| Rollback undoes the INSERT | That is MariaDB's responsibility |
| `frappe.get_doc()` returns the correct doc | That is the ORM's responsibility |
| The field exists in the doctype | That is the migration's responsibility |

### Example of the distinction

```python
# ❌ Tests ORM behavior — adds no value
def test_supplier_can_be_inserted(self):
    supplier = create_supplier()
    self.assertTrue(frappe.db.exists("Supplier", supplier))

# ✅ Tests a business rule
def test_invoice_rejected_when_currency_mismatch(self):
    # Rule: an XML in MXN cannot be applied to a PO in USD
    cfdi = make_mock_cfdi(currency="MXN")
    po_data = make_mock_po(currency="USD")

    result = validate_supplier_invoice(cfdi, po_data)

    self.assertFalse(result.is_valid)
    self.assertIn("MXN", result.error)
    self.assertIn("USD", result.error)
```

---

## Builder Pattern — creating test data

Every integration test that needs DB records must use builders instead of creating doctypes inline.

### build() vs create()

```python
def create_supplier(**overrides) -> str:
    """Insert the record into DB. Idempotent: returns existing name if already present."""
    data = {"supplier_name": "Test Supplier", **overrides}
    name = data["supplier_name"]
    if frappe.db.exists("Supplier", name):
        return name
    frappe.get_doc({"doctype": "Supplier", **data}).insert(ignore_permissions=True)
    return name


def build_supplier(**overrides) -> frappe.model.document.Document:
    """Return a Document object WITHOUT inserting it into DB. For Strategy A (mock-based) tests."""
    data = {"doctype": "Supplier", "supplier_name": "Test Supplier", **overrides}
    return frappe.get_doc(data)
```

Use `create_supplier()` (Strategy B) when the test needs a real record in the DB.
Use `build_supplier()` (Strategy A) when the test needs to pass a document object to a function without touching the DB.

### test_records.json vs builders

The official Frappe approach uses `test_records.json` — static JSON fixtures loaded once at the start of the test run. Builders are strictly better for custom apps:

| | `test_records.json` | Builders |
|---|---|---|
| Idempotent | ✗ Fails on re-run if record exists | ✓ Guard check returns existing record |
| Per-test overrides | ✗ Fixed data for all tests | ✓ `**overrides` per call |
| Shared state | ✗ All tests share the same fixture | ✓ Each test creates what it needs |
| Explicit dependencies | ✗ Implicit — tests assume the fixture loaded | ✓ Explicit — `create_supplier()` in setUp |

---

## Checklist before committing a test

- [ ] Test runs in isolation: `bench --site your-test-site.localhost run-tests --skip-test-records --module <module>`
- [ ] Test runs **twice in a row** without failing (idempotent)
- [ ] Test **does not assume** any record pre-exists in the DB (creates everything via builders)
- [ ] Builders use the correct guard (same key they insert)
- [ ] No hardcoded `name` in child rows
- [ ] Integration tests inherit from `FrappeTestCase`
- [ ] `tearDown` calls `frappe.db.rollback()` (handled by `FrappeTestCase` — do not duplicate)
- [ ] Disabled tests use `@unittest.skip("reason")`, not `_test_` prefix
- [ ] The test asserts a business rule, not ORM/framework behavior
