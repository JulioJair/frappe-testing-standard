#!/usr/bin/env bash
# Installs the frappe-testing Claude Code skill into the current Frappe app.
# Run from the root of your app:
#
#   bash <(curl -s https://raw.githubusercontent.com/JulioJair/frappe-testing-standard/main/install.sh)
#
# Options:
#   --full    Also copies templates/ and builders/ into your_app/tests/

set -e

REPO="https://raw.githubusercontent.com/JulioJair/frappe-testing-standard/main"
SKILL_DIR=".claude/skills/frappe-testing"

# ── Detect app name ───────────────────────────────────────────────────────────
APP_NAME=$(find . -maxdepth 2 -name "__init__.py" -path "*/*/__init__.py" \
  | head -1 | cut -d'/' -f2)

if [ -z "$APP_NAME" ]; then
  echo "Error: could not detect app name. Run this from your app root."
  exit 1
fi

echo "Detected app: $APP_NAME"

# ── Install skill ─────────────────────────────────────────────────────────────
echo "Installing Claude Code skill..."
mkdir -p "$SKILL_DIR"
curl -sS "$REPO/.claude/skills/frappe-testing/SKILL.md" -o "$SKILL_DIR/SKILL.md"
echo "  ✓ $SKILL_DIR/SKILL.md"

# ── Full install (--full) ─────────────────────────────────────────────────────
if [[ "$1" == "--full" ]]; then
  TESTS_DIR="$APP_NAME/tests"
  echo "Copying templates and builders..."

  mkdir -p "$TESTS_DIR/builders"
  for f in company_builder supplier_builder item_builder purchase_order_builder __init__; do
    curl -sS "$REPO/builders/$f.py" -o "$TESTS_DIR/builders/$f.py" 2>/dev/null && echo "  ✓ $TESTS_DIR/builders/$f.py"
  done

  mkdir -p "$TESTS_DIR"
  curl -sS "$REPO/templates/base-test-class.py" -o "$TESTS_DIR/base.py"
  echo "  ✓ $TESTS_DIR/base.py"

  mkdir -p ".github/workflows"
  curl -sS "$REPO/ci/unit-tests.yml" -o ".github/workflows/unit-tests.yml"
  echo "  ✓ .github/workflows/unit-tests.yml"
  echo ""
  echo "Next: edit .github/workflows/unit-tests.yml and set FRAPPE_VERSION for your app."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Done. In Claude Code, type /frappe-testing to activate the skill."
echo "Docs: https://github.com/JulioJair/frappe-testing-standard"
