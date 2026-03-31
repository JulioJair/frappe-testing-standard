# Frappe Testing Standard

A systematic approach to writing reliable, idempotent tests for Frappe/ERPNext custom apps.

---

## The Problem

Every Frappe custom app eventually develops the same testing symptoms:

- Tests that pass on first run but fail on the second (`Duplicate Entry` errors)
- No distinction between tests that need a real DB and tests that don't
- Empty `test_*.py` placeholder files giving a false sense of coverage
- `setUp` that contaminates shared data, making tests order-dependent
- Tests that can only run sequentially because they rely on state left by the previous test

The root cause: Frappe doesn't define a testing strategy. Each team invents their own — usually copying patterns from the framework's own tests, which are built for a different context. The result is a test suite that nobody trusts.

---

## The Solution: A/B/C Decision Tree

Before writing a single test, answer one question: **what does the function under test do?**

```
What does the function under test do?
│
├─► Pure logic only (calculations, transformations, in-memory validations)
│   └─► STRATEGY A — Unit test with mocks
│       → Runs in CI without bench, without a DB
│
├─► Queries or writes to DB (frappe.db.get_value, frappe.get_doc, .insert)
│   └─► STRATEGY B — Integration test with real DB + rollback
│       → Requires a dedicated test site, never the dev site
│
└─► Full end-to-end flow (external APIs, background jobs, PDF/XML generation)
    └─► STRATEGY C — Conditional test with @skipUnless
        → Skipped by default, opt-in with an env variable
```

The decision is deterministic. If you know what the function does, you know which strategy to use.

> **Why A/B/C and not "unit/integration/e2e"?** In the Frappe ecosystem those terms are overloaded — teams routinely call anything that runs with `bench run-tests` a "unit test", regardless of whether it hits the DB. The letter forces the right question: *what does the function do?* — not *what do I feel like calling this test?*

---

## What's in this repo

```
frappe-testing-standard/
├── README.md                         ← you are here
├── decision-tree.md                  ← full A/B/C guide with rules and examples
├── anti-patterns.md                  ← 7 real bugs found in production, with fixes
├── templates/
│   ├── strategy-a-unit.py            ← Strategy A template (mock-based)
│   ├── strategy-b-integration.py     ← Strategy B template (real DB + rollback)
│   └── base-test-class.py            ← FrappeTestCase base class
├── builders/
│   ├── company_builder.py            ← idempotent test data builder — Company
│   ├── supplier_builder.py           ← idempotent test data builder — Supplier
│   ├── item_builder.py               ← idempotent test data builder — Item
│   └── purchase_order_builder.py     ← idempotent test data builder — Purchase Order
└── ci/
    ├── unit-tests.yml                ← GitHub Actions workflow for Strategy A
    └── unit-tests.txt.example        ← example module list for CI
```

---

## How to adopt this in your app

### 1. Copy the base class

Copy `templates/base-test-class.py` to `your_app/tests/base.py`. All integration tests (Strategy B) inherit from `FrappeTestCase`.

### 2. Add builders for your domain

Copy the builders from `builders/` to `your_app/tests/builders/`. Add builders for the ERPNext doctypes your tests rely on. Follow the contract in `decision-tree.md`.

### 3. Set up a dedicated test site

Never run integration tests against your dev site — it contaminates data and causes `Duplicate Entry` on repeated runs:

```bash
bench new-site your-test-site.localhost --install-app erpnext --install-app your_app
bench --site your-test-site.localhost run-tests --skip-test-records --app your_app
```

### 4. Add the CI workflow for unit tests

Copy `ci/unit-tests.yml` to `.github/workflows/unit-tests.yml`. Create a `.github/unit-tests.txt` that lists the test modules for Strategy A (no DB needed). See `ci/unit-tests.txt.example` for the format.

---

## The 7 anti-patterns this standard eliminates

| Anti-pattern | Consequence |
|---|---|
| Guard checks wrong key in setUp | Duplicate Entry on second run |
| Hardcoded `name` in child rows | IntegrityError when two rows share the same name |
| Copy-pasted setUp across classes | Bug propagates to multiple files |
| Tests disabled with `_test_` prefix | Coverage silently lost |
| `side_effect` without order comments | Breaks when internal call order changes |
| Order-dependent test methods | Test B fails if Test A didn't run first |
| Empty placeholder `test_*.py` files | False sense of coverage |

See `anti-patterns.md` for each bug in detail, with real code and the fix.

---

## Why this matters

The problem is universal in the Frappe ecosystem. Any team with a custom app has these symptoms. This standard gives you:

- A **deterministic decision rule** (A/B/C) — no more debates about what kind of test to write
- **CI without bench** — Strategy A tests run in GitHub Actions in ~30 seconds with no DB
- **Idempotent builders** — tests can run in any order, any number of times
- A **base class** that enforces rollback — no more contaminated test state

---

## How this compares to existing resources

### vs Official Frappe documentation

The official docs ([docs.frappe.io/testing](https://docs.frappe.io)) and community tutorials cover `bench run-tests`, `setUp/tearDown`, `test_records.json`, and `frappe.in_test`. This standard is complementary — it fills gaps the official docs leave open:

| | Official docs | This standard |
|---|---|---|
| `bench run-tests` and basic unittest | ✓ | ✓ |
| `test_records.json` fixtures | ✓ | Note: builders are strictly better (see below) |
| **Mocking strategy (Strategy A)** | ✗ not mentioned | ✓ full pattern with `@patch` rules |
| **CI without bench** (pip install + pytest) | ✗ | ✓ GitHub Actions matrix v13/v14/v15 |
| **Deterministic A/B/C decision rule** | ✗ | ✓ |
| **Builder pattern** (idempotent, with overrides) | ✗ | ✓ |
| **Anti-patterns with real code** | ✗ | ✓ 7 bugs found in 155 production files |

### vs pytest-based skills (e.g. the sergio-bershadsky/frappe-test skill)

Some community skills use pytest with factory fixtures. This standard uses `unittest.TestCase` intentionally:

| | pytest-based skills | This standard |
|---|---|---|
| Compatible with `bench run-tests` natively | ✗ requires extra config | ✓ |
| Session/module/function-scoped fixtures | ✓ | ✓ (via `FrappeTestCase` + builders) |
| `build()` without DB insert | ✓ | ✓ (see Builder Pattern section) |
| **CI without bench** | ✗ | ✓ |
| **Deterministic A/B/C decision rule** | ✗ | ✓ |
| **Anti-patterns with contamination cycle** | ✗ | ✓ AP-01 with full cycle explanation |
| **Claude Code skill** | ✗ | ✓ `.claude/skills/frappe-testing/` |

**Why not pytest?** `bench run-tests` uses unittest discovery. Adopting pytest requires project-level configuration that not every team will set up. For a standard aimed at community adoption, unittest has less friction. The CI workflow already runs pytest on top of unittest files — both are compatible.

