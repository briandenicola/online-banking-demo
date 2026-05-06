#!/usr/bin/env bash
# seed-data.sh — Populate local development services with demo data
# Prerequisites: docker-compose services running (user:6001, account:6002, transaction:6003, transfer:6004)
set -euo pipefail

# --- Configuration ---
USER_SERVICE="http://localhost:6001"
ACCOUNT_SERVICE="http://localhost:6002"
TRANSACTION_SERVICE="http://localhost:6003"
TRANSFER_SERVICE="http://localhost:6004"

# --- Color helpers ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}ℹ ${NC} $1"; }
success() { echo -e "${GREEN}✔ ${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠ ${NC} $1"; }
error()   { echo -e "${RED}✖ ${NC} $1"; }
header()  { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }

# --- Helper: register a user (idempotent — tolerates "already exists") ---
register_user() {
  local username="$1" email="$2" password="$3" first="$4" last="$5"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "${USER_SERVICE}/api/users/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${username}\",\"email\":\"${email}\",\"password\":\"${password}\",\"firstName\":\"${first}\",\"lastName\":\"${last}\"}")

  local http_code body
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "201" ]]; then
    success "Registered user: ${username} (${email})"
  elif [[ "$http_code" == "400" ]] && echo "$body" | grep -qi "already"; then
    warn "User ${username} already exists — skipping"
  else
    error "Failed to register ${username} (HTTP ${http_code}): ${body}"
    return 1
  fi
}

# --- Helper: login and capture token ---
login_user() {
  local username="$1" password="$2"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "${USER_SERVICE}/api/users/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${username}\",\"password\":\"${password}\"}")

  local http_code body
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" != "200" ]]; then
    error "Login failed for ${username} (HTTP ${http_code}): ${body}"
    return 1
  fi

  # Extract token from JSON response
  echo "$body" | grep -o '"[Tt]oken":"[^"]*"' | head -1 | cut -d'"' -f4
}

# --- Helper: create account (returns account JSON) ---
create_account() {
  local token="$1" account_type="$2" initial_balance="$3"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "${ACCOUNT_SERVICE}/api/accounts" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${token}" \
    -d "{\"accountType\":\"${account_type}\",\"initialBalance\":${initial_balance},\"currency\":\"USD\"}")

  local http_code body
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
    success "Created ${account_type} account (balance: \$${initial_balance})"
    echo "$body"
  else
    error "Failed to create ${account_type} account (HTTP ${http_code}): ${body}"
    return 1
  fi
}

# --- Helper: create transaction ---
create_transaction() {
  local token="$1" account_id="$2" amount="$3" type="$4" description="$5" category="$6"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "${TRANSACTION_SERVICE}/api/transactions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${token}" \
    -d "{\"accountId\":\"${account_id}\",\"amount\":${amount},\"type\":\"${type}\",\"description\":\"${description}\",\"currency\":\"USD\",\"category\":\"${category}\"}")

  local http_code body
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
    success "Transaction: ${type} \$${amount} — ${description}"
  else
    error "Transaction failed (HTTP ${http_code}): ${body}"
    return 1
  fi
}

# --- Helper: create transfer ---
create_transfer() {
  local token="$1" from_account="$2" to_account="$3" amount="$4" description="$5"

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "${TRANSFER_SERVICE}/api/transfers" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${token}" \
    -d "{\"fromAccountNumber\":\"${from_account}\",\"toAccountNumber\":\"${to_account}\",\"amount\":${amount},\"description\":\"${description}\"}")

  local http_code body
  http_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
    success "Transfer: \$${amount} from ${from_account} → ${to_account}"
  else
    error "Transfer failed (HTTP ${http_code}): ${body}"
    return 1
  fi
}

# --- Extract field from JSON (lightweight, no jq dependency) ---
json_field() {
  local json="$1" field="$2"
  echo "$json" | grep -o "\"${field}\":\"[^\"]*\"" | head -1 | cut -d'"' -f4
}

# =============================================================================
# MAIN SCRIPT
# =============================================================================
echo -e "${GREEN}🏦 Online Banking Demo — Seed Data${NC}"
echo "   Populating local services with demo data..."

# --- Step 1: Register demo users ---
header "Step 1: Registering demo users"
register_user "alice"  "alice@example.com"  "Password123!" "Alice" "Johnson"
register_user "bob"    "bob@example.com"    "Password123!" "Bob"   "Smith"
register_user "admin"  "admin@example.com"  "Password123!" "Admin" "User"

# --- Step 2: Login to get JWT tokens ---
header "Step 2: Authenticating users"
ALICE_TOKEN=$(login_user "alice" "Password123!")
success "Alice authenticated"
BOB_TOKEN=$(login_user "bob" "Password123!")
success "Bob authenticated"
ADMIN_TOKEN=$(login_user "admin" "Password123!")
success "Admin authenticated"

# --- Step 3: Create accounts ---
header "Step 3: Creating bank accounts"

info "Creating Alice's accounts..."
ALICE_CHECKING=$(create_account "$ALICE_TOKEN" "checking" 5000)
ALICE_SAVINGS=$(create_account "$ALICE_TOKEN" "savings" 10000)

info "Creating Bob's accounts..."
BOB_CHECKING=$(create_account "$BOB_TOKEN" "checking" 3000)
BOB_SAVINGS=$(create_account "$BOB_TOKEN" "savings" 7500)

info "Creating Admin's accounts..."
ADMIN_CHECKING=$(create_account "$ADMIN_TOKEN" "checking" 1000)

# Extract account IDs and numbers for subsequent operations
ALICE_CHECKING_ID=$(json_field "$ALICE_CHECKING" "id")
ALICE_SAVINGS_ID=$(json_field "$ALICE_SAVINGS" "id")
ALICE_CHECKING_NUM=$(json_field "$ALICE_CHECKING" "accountNumber")

BOB_CHECKING_ID=$(json_field "$BOB_CHECKING" "id")
BOB_SAVINGS_ID=$(json_field "$BOB_SAVINGS" "id")
BOB_CHECKING_NUM=$(json_field "$BOB_CHECKING" "accountNumber")

# --- Step 4: Create sample transactions ---
header "Step 4: Generating sample transactions"

info "Alice's transactions..."
create_transaction "$ALICE_TOKEN" "$ALICE_CHECKING_ID" 1500.00 "deposit"    "Payroll deposit"           "income"
create_transaction "$ALICE_TOKEN" "$ALICE_CHECKING_ID" 45.99   "withdrawal" "Grocery store purchase"    "groceries"
create_transaction "$ALICE_TOKEN" "$ALICE_CHECKING_ID" 120.00  "withdrawal" "Electric bill payment"     "utilities"
create_transaction "$ALICE_TOKEN" "$ALICE_SAVINGS_ID"  500.00  "deposit"    "Monthly savings transfer"  "savings"

info "Bob's transactions..."
create_transaction "$BOB_TOKEN" "$BOB_CHECKING_ID" 2200.00 "deposit"    "Freelance payment"        "income"
create_transaction "$BOB_TOKEN" "$BOB_CHECKING_ID" 89.50   "withdrawal" "Restaurant dinner"        "dining"
create_transaction "$BOB_TOKEN" "$BOB_CHECKING_ID" 250.00  "withdrawal" "Car insurance premium"    "insurance"
create_transaction "$BOB_TOKEN" "$BOB_SAVINGS_ID"  1000.00 "deposit"    "Emergency fund deposit"   "savings"

# --- Step 5: Create a transfer between Alice and Bob ---
header "Step 5: Creating inter-account transfer"

if [[ -n "$ALICE_CHECKING_NUM" && -n "$BOB_CHECKING_NUM" ]]; then
  create_transfer "$ALICE_TOKEN" "$ALICE_CHECKING_NUM" "$BOB_CHECKING_NUM" 200.00 "Splitting dinner bill"
else
  warn "Could not extract account numbers — skipping transfer"
fi

# --- Done ---
header "Seed Complete"
echo -e "${GREEN}🎉 Demo data seeded successfully!${NC}"
echo ""
echo "  Demo credentials:"
echo "    alice / Password123!  (checking + savings)"
echo "    bob   / Password123!  (checking + savings)"
echo "    admin / Password123!  (checking)"
echo ""
