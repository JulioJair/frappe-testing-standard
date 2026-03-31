---
name: frappe-testing
description: "Testing patterns and templates for Frappe/ERPNext custom apps. Use when writing, fixing, or reviewing tests. Covers unit tests (mock-based, Strategy A), integration tests (real DB with rollback, Strategy B), conditional tests (Strategy C), Test Data Builder pattern, base test class, test generation protocol, anti-patterns, and CI setup. Triggers: write test, add test, test coverage, fix failing test, setUp, tearDown, frappe.db.rollback, unittest, mock, patch, test site, bench run-tests, builder, create_supplier, create_item, create_purchase_order, base test class, FrappeTestCase, idempotent test, Duplicate Entry test, Strategy A, Strategy B."
---

# Frappe Testing Standard — Skill

> **This skill is authoritative for testing in this app.**
> If existing tests contradict this document, refactor the tests.
> Do not invent new patterns unless explicitly required.

> **Derived from a real audit of test files in a production Frappe app.**
> See `anti-patterns.md` for the 7 bugs found and their fixes.

---

## 1. Execution environment

```bash
# ALWAYS against the test site, not the dev site
bench --site your-test-site.localhost run-tests --skip-test-records --app your_app

# Specific module
bench --site your-test-site.localhost run-tests --skip-test-records \
  --module your_app.server.my_module.test_my_module

# If tests fail due to dirty data → restore clean DB from your backup
bench --site your-test-site.localhost --force restore <backup.sql.gz>
```

> ⚠️ **Never run against the dev site.** It contaminates development data and causes
> `Duplicate Entry` errors on subsequent runs.

---

## 2. Decision tree — which strategy to use?

```
What does the function under test do?
│
├─► Pure logic only (calculations, transformations, in-memory validations)
│   └─► STRATEGY A — Unit test with mocks
│       → Runs in CI without bench or DB
│
├─► Queries or writes to DB (frappe.db.get_value, frappe.get_doc, .insert)
│   └─► STRATEGY B — Integration test with real DB + rollback
│
├─► Full end-to-end flow (external APIs, background jobs, XML, multi-doc workflows)
│   └─► STRATEGY C — Conditional test with @skipUnless
│
└─► test_*.py file exists but is empty (placeholder)
    └─► Evaluate if the functionality deserves tests → if yes, choose A or B above
```

---

## 3. Strategy A — Unit test with mocks

Use when the function has no real external side effects. The test does not touch the DB.

### Template

```python
import unittest
from unittest.mock import patch, MagicMock
import frappe


class TestMyFunction(unittest.TestCase):

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    @patch("your_app.server.my_module.my_module.frappe.db.set_value")
    def test_happy_path(self, mock_set, mock_get):
        # Arrange: side_effect in the same order the function calls them
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

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    def test_early_return_when_none(self, mock_get):
        mock_get.return_value = None
        doc = MagicMock()

        from your_app.server.my_module.my_module import my_function
        my_function(doc)

        mock_get.assert_called_once()  # did not continue processing

    @patch("your_app.server.my_module.my_module.frappe.db.get_value")
    def test_raises_validation_error(self, mock_get):
        mock_get.return_value = "bad-state"
        doc = MagicMock()

        from your_app.server.my_module.my_module import my_function
        with self.assertRaises(frappe.ValidationError):
            my_function(doc)
```

### Critical rules — Strategy A

- The path in `@patch` must be **where the name is used**, not where it is defined.
  - ✅ `@patch("your_app.server.foo.foo.frappe.db.get_value")`
  - ❌ `@patch("frappe.db.get_value")` (patches the original, not the local import)
- `@patch` parameters are injected in **reverse** order of decorators (last decorator = first parameter).
- `side_effect` is positional: if the internal function reorders calls, the test breaks. Document the order with inline comments.
- Do not use `frappe.db.rollback()` in tearDown — there is nothing to clean up.
- **If a mock assertion is your only way to verify correctness, the function needs refactoring.** `assert_called_once_with(set_value, ...)` tests *how* the function works, not *what* it produces. Extract the calculation into a pure function and assert on its return value instead. The need for a mock assertion is a signal, not a solution.
- Mock `frappe.db.commit` if the code under test calls it explicitly — an un-mocked commit persists data that `tearDown`'s rollback cannot undo:

```python
@patch("your_app.server.my_module.my_module.frappe.db.commit")
def test_something(self, mock_commit):
    # commits are intercepted — no partial data persists to DB
    my_function(doc)
    mock_commit.assert_called_once()
```

### frappe.flags.in_test

`bench run-tests` sets `frappe.flags.in_test = True` automatically. Use in **production code** to skip expensive side effects during test runs:

```python
def submit_to_tax_authority(doc):
    if frappe.flags.in_test:
        return  # skip external API call in test context
    # ... real submission logic
```

Useful for: email sending, external API calls, PDF/XML generation, background job enqueueing. Not a substitute for mocking — if the function has logic to verify, use `@patch` instead.

---

## 4. Strategy B — Integration test with real DB

Use when the function runs queries or inserts real records.

### Template with safe setUp

```python
import unittest
import frappe

from your_app.tests.base import FrappeTestCase
from your_app.tests.builders.supplier_builder import create_supplier
from your_app.tests.builders.item_builder import create_item


class TestMyDocType(FrappeTestCase):

    def setUp(self):
        super().setUp()
        self._create_test_data()

    # ─── Setup helpers ────────────────────────────────────────────────────────

    def _create_test_data(self):
        self.supplier_name = create_supplier()
        self._create_main_doc()

    def _create_main_doc(self):
        # RULE: the guard ALWAYS checks the same key it is about to insert
        if frappe.db.exists("My DocType", "TEST-DOC-001"):
            self.test_doc = frappe.get_doc("My DocType", "TEST-DOC-001")
            return
        self.test_doc = self.insert_doc(
            "My DocType",
            name="TEST-DOC-001",
            supplier=self.supplier_name,
        )

    # ─── Tests ────────────────────────────────────────────────────────────────

    def test_validate_passes_with_valid_data(self):
        self.test_doc.reload()
        self.test_doc.validate()  # must not raise

    def test_validate_raises_with_invalid_state(self):
        self.test_doc.some_field = "invalid"
        with self.assertRaises(frappe.ValidationError):
            self.test_doc.validate()
```

### Critical rules — Strategy B

**1. The guard checks the SAME key it inserts**
```python
# ✅ CORRECT
def _create_zone(self):
    if frappe.db.exists("Freight Zone", "ZONE-001"):   # same key
        return
    frappe.get_doc({"city": "ZONE-001", ...}).insert()

# ❌ WRONG — the most common bug in Frappe test suites
def _create_zone(self):
    if frappe.db.exists("Freight Zone", "ZONE-002"):   # DIFFERENT key
        return
    frappe.get_doc({"city": "ZONE-001", ...}).insert()  # Duplicate Entry on 2nd run
```

**2. Never hardcode `name` in child rows**
```python
# ✅ CORRECT — Frappe generates child names automatically
"items": [
    {"doctype": "Purchase Order Item", "item_code": "TEST-ITEM-001", "qty": 1},
]

# ❌ WRONG — IntegrityError when two rows share the same name
"items": [
    {"doctype": "Purchase Order Item", "name": "abc123", "item_code": "TEST-ITEM-001"},
    {"doctype": "Purchase Order Item", "name": "abc123", "item_code": "TEST-ITEM-002"},
]
```

**3. If setUp fails, tearDown does not run → contamination cycle**
```
setUp fails (Duplicate Entry)
  → tearDown does NOT run (Python unittest contract)
  → record stays in DB
  → next setUp also fails
  → all tests in the class fail permanently on that DB
```
Fix: correct guards + restore clean test site from backup.

**4. `frappe.db.rollback()` only undoes uncommitted changes**

If `.insert()` was committed during setUp (by an implicit flush), the tearDown rollback will not undo it. Keep a clean test site — restore from backup when state is corrupted.

---

## 5. Strategy C — Conditional integration test

For tests requiring external services, background workers, or multi-doc flows.

```python
import os
import unittest

RUN_INTEGRATION_TESTS = bool(os.environ.get("RUN_INTEGRATION_TESTS"))


class TestExternalWorkflow(unittest.TestCase):

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    @unittest.skipUnless(RUN_INTEGRATION_TESTS, "Requires external service: RUN_INTEGRATION_TESTS=1")
    def test_end_to_end_submission(self):
        ...
```

> These tests never run in standard `bench run-tests`. They require:
> `RUN_INTEGRATION_TESTS=1 bench --site your-test-site.localhost run-tests ...`

---

## 6. Shared constants

Centralize test constants in a single module. **Never hardcode** the same values across multiple test files.

```python
# your_app/tests/constants.py
import os

RUN_INTEGRATION_TESTS = bool(os.environ.get("RUN_INTEGRATION_TESTS"))

# Company and currency — adjust for your app
TEST_COMPANY   = "Test Company"
TEST_CURRENCY  = "USD"

# Generic tax ID placeholders (adjust for your country's format)
TEST_TAX_ID_GENERIC = "GENERIC-TAX-ID"   # e.g. XAXX010101000 for Mexico
TEST_TAX_ID_COMPANY = "COMPANY-TAX-ID"   # your test company's tax ID
```

```python
# Usage in tests
from your_app.tests.constants import TEST_COMPANY, TEST_CURRENCY
```

---

## 7. Anti-patterns found in real apps

See `anti-patterns.md` for all cases with real code and fixes.

| Anti-pattern | Consequence |
|---|---|
| Guard checks wrong key in setUp | Duplicate Entry on second run |
| Hardcoded `name` in child rows | IntegrityError on insert |
| Copy-pasted setUp across classes | Bug propagates to multiple files |
| `_test_` prefix to disable tests | Coverage silently lost |
| `side_effect` without order comments | Breaks on internal call reorder |
| Order-dependent test methods | Test B fails if Test A didn't run first |
| 134 empty placeholder files | False sense of coverage |

---

## 8. Structure of a new test file

```
your_app/
└── server/
    └── my_feature/
        ├── my_feature.py            ← code under test
        └── test_my_feature.py       ← test alongside the feature

your_app/
└── your_app/
    └── doctype/
        └── my_doctype/
            ├── my_doctype.py
            └── test_my_doctype.py   ← test alongside the doctype
```

### Class and file naming

```python
# File: test_my_feature.py
class TestMyFeature(unittest.TestCase):  # PascalCase, Test prefix
    ...
```

---

## 9. Test Data Builder Pattern

Every integration test that needs DB data **must use builders** instead of creating doctypes inline.

### Location

```
your_app/tests/builders/
├── __init__.py
├── company_builder.py
├── supplier_builder.py
├── item_builder.py
└── purchase_order_builder.py
```

### Builder contract

```python
# your_app/tests/builders/supplier_builder.py
import frappe


def create_supplier(**overrides) -> str:
    """
    Create a test Supplier. Idempotent: returns existing name if already present.
    Returns: the Supplier name.
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
```

### build() vs create()

```python
def create_supplier(**overrides) -> str:
    """Insert into DB. Idempotent. Use in Strategy B tests."""
    data = {"supplier_name": "Test Supplier", **overrides}
    name = data["supplier_name"]
    if frappe.db.exists("Supplier", name):
        return name
    frappe.get_doc({"doctype": "Supplier", **data}).insert(ignore_permissions=True)
    return name


def build_supplier(**overrides) -> "frappe.model.document.Document":
    """Return a Document WITHOUT inserting it. Use in Strategy A (mock-based) tests."""
    data = {"doctype": "Supplier", "supplier_name": "Test Supplier", **overrides}
    return frappe.get_doc(data)
```

Use `create_*()` when the test needs a persisted record. Use `build_*()` when a function accepts a doc object and the test should not touch the DB.

### Optional convenience methods

```python
def create_supplier_batch(count: int, **overrides) -> list[str]:
    """Create `count` suppliers with unique names. Useful for list/filter tests."""
    return [create_supplier(supplier_name=f"Test Supplier {i:03d}", **overrides) for i in range(count)]


def create_submitted_invoice(**overrides):
    """Create and submit an invoice. Use only when testing post-submit logic."""
    doc = frappe.get_doc({"doctype": "Sales Invoice", **overrides})
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc
```

Add these only when two or more tests need them — don't pre-create convenience methods speculatively.

**Builder rules:**
1. Accepts `**overrides` — the caller controls only what matters for that test
2. Safe defaults — works with no arguments
3. Idempotent — if the record already exists, returns the name without failing
4. Returns the document `name` — the test can use it to link records
5. Lives in `tests/builders/`, never inline in the test
6. Does not call `frappe.db.commit()` — tearDown rollback cleans it up

### Usage in a test

```python
from your_app.tests.builders.supplier_builder import create_supplier
from your_app.tests.builders.item_builder import create_item

class TestInvoiceValidation(FrappeTestCase):

    def setUp(self):
        super().setUp()
        self.supplier = create_supplier(supplier_name="Specific Vendor Ltd")
        self.item = create_item(item_code="RAW-001")
```

---

## 10. Base Test Class

All integration tests (Strategy B) must inherit from `FrappeTestCase`.

```python
# your_app/tests/base.py
import unittest
import frappe


class FrappeTestCase(unittest.TestCase):
    """
    Base class for integration tests in Frappe custom apps.

    Guarantees:
    - Administrator user in setUp and tearDown
    - frappe.db.rollback() in tearDown (always, even if the test failed)
    - insert_doc() helper with ignore_permissions=True
    """

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def insert_doc(self, doctype: str, **fields):
        """Create and insert a document with ignore_permissions=True. Returns the Document."""
        doc = frappe.get_doc({"doctype": doctype, **fields})
        doc.insert(ignore_permissions=True)
        return doc
```

Strategy A tests can inherit from `unittest.TestCase` directly — they do not need `FrappeTestCase`.

### Permission testing

Testing role-based access is out of scope for this standard's v1. The pattern involves:

```python
frappe.set_user("limited_user@example.com")
with self.assertRaises(frappe.PermissionError):
    frappe.get_doc("My DocType", doc_name)
```

Ensure you restore `Administrator` in tearDown (handled automatically by `FrappeTestCase`).

---

## 11. What to test — business rules, not Frappe internals

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
    doc = MagicMock()
    doc.currency = "MXN"
    mock_get.return_value = "USD"  # PO currency

    with self.assertRaises(frappe.ValidationError) as ctx:
        validate_currency_match(doc)

    self.assertIn("MXN", str(ctx.exception))
    self.assertIn("USD", str(ctx.exception))
```

---

## 12. Test generation protocol

When asked to generate tests for a function, always follow this order:

### Step 1 — Architecture reasoning

Before writing a single line of code, answer:
- What business rule is being tested?
- Does the function touch the DB or is it pure logic? → determines Strategy A or B
- What domain entities does it need? → determines which builders to use
- What are the critical cases? → happy path + edge case + failure condition

**Mock assertion check:** if the only way to verify correctness is `assert_called_once_with(set_value, ...)`, the function mixes logic with side effects. Before generating tests, flag this:

> "This function mixes a calculation with a DB write. The test would only verify that `set_value` was called — not that the value is correct. I recommend extracting the calculation first:
> ```python
> def _calculate_X(inputs) -> float: ...  # pure, testable directly
> def update_X(doc): frappe.db.set_value(..., _calculate_X(...))  # thin wrapper
> ```
> Want me to do the extraction, or generate mock-based tests as-is?"

If the user declines the refactor, generate the mock-based test — but include a `# TODO: extract _calculate_X for behavior-level testing` comment in the test file.

### Step 2 — Test design

Describe in plain language what each test method will do before writing it:
- `test_<happy_path>` → given X, the result is Y
- `test_<edge_case>` → given X with a boundary condition, the result is Z
- `test_<failure>` → given invalid X, raises ValidationError with message M

### Step 3 — Code

Implement following the Strategy A or B templates in this skill.

### Step 4 — Stability explanation

For each generated test, explain:
- Why it does not depend on pre-existing data
- Why it runs idempotently (second run = same result)
- Why tearDown cleans up state completely

---

## 13. Semantic assertion helpers

When the same group of assertions appears in 2+ tests, extract it into a standalone function.

```python
# your_app/tests/assertions.py
import frappe


def assert_document_submitted(testcase, doc):
    """Document is submitted (docstatus=1)."""
    testcase.assertEqual(doc.docstatus, 1)


def assert_document_cancelled(testcase, doc):
    """Document is cancelled (docstatus=2)."""
    testcase.assertEqual(doc.docstatus, 2)


def assert_validation_error_contains(testcase, exc_info, *keywords):
    """ValidationError message contains all expected keywords."""
    message = str(exc_info.exception)
    for keyword in keywords:
        testcase.assertIn(keyword, message)
```

```python
# Usage — reads like business intent
from your_app.tests.assertions import assert_document_submitted

assert_document_submitted(self, invoice)

# Instead of repeating:
self.assertEqual(invoice.docstatus, 1)
```

**Rules:**
- Create `assertions.py` only when a group of asserts appears in 2+ tests
- Functions take `(testcase, subject, ...)` — `testcase` is always first
- Name after business outcomes: `assert_invoice_paid` not `assert_status_equals_paid`

---

## 14. Coverage priorities

Not all modules are equal. Cover what breaks money or operations first.

| Level | Types of modules | Why |
|---|---|---|
| **1 — Critical** | Financial transactions, tax compliance, payment processing | Incorrect output has direct monetary or legal impact |
| **2 — Operations** | Document workflows, state machines, integrations | Flow errors block operations |
| **3 — Utilities** | Helpers, formatters, date utils, rule evaluators | Supporting logic, lower blast radius |

Do not chase 100% coverage. Prioritize Level 1 first.

---

## 15. Engineering constraints

| Constraint | Implication |
|---|---|
| Tests run on an isolated DB (`your-test-site.localhost`) | Never assume any record exists |
| No pre-seeded data required | Each test creates everything it needs via builders |
| No manual setup required | `bench run-tests` must be sufficient |
| Idempotent | Running twice in a row = same result |
| No order dependency | Any test can run in any order |

---

## 16. Checklist before committing a test

- [ ] Test runs in isolation: `bench --site your-test-site.localhost run-tests --skip-test-records --module <module>`
- [ ] Test runs **twice in a row** without failing (idempotent)
- [ ] Test **does not assume** any record exists in the DB (creates everything via builders)
- [ ] Builders use the correct guard (same key they insert)
- [ ] No hardcoded `name` in child rows
- [ ] No constants duplicated from another test file
- [ ] Integration tests inherit from `FrappeTestCase`
- [ ] `tearDown` in `FrappeTestCase` does rollback (do not duplicate in subclasses)
- [ ] Disabled methods use `@unittest.skip("reason")`, not `_test_` prefix
- [ ] The test asserts a business rule, not ORM/framework behavior
