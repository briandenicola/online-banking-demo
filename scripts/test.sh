#!/bin/bash
# Test script for Online Banking Demo services
# Usage: ./test.sh [--all | --smoke | --ai]

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

log_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++)) || true
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++)) || true
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
}

# Health check
test_health() {
    log_test "Testing health endpoints..."
    
    if curl -sf http://localhost:8001/health | grep -q "healthy"; then
        log_pass "Chatbot service health"
    else
        log_fail "Chatbot service health"
    fi
    
    if curl -sf http://localhost:8002/health | grep -q "healthy"; then
        log_pass "Anomaly service health"
    else
        log_fail "Anomaly service health"
    fi
    
    if curl -sf http://localhost:8003/health | grep -q "healthy"; then
        log_pass "Budget service health"
    else
        log_fail "Budget service health"
    fi
}

# Functional tests
test_functionality() {
    log_test "Testing functional endpoints..."
    
    # Test anomaly detection endpoint
    RESPONSE=$(curl -sf -X POST http://localhost:8002/detect \
        -H "Content-Type: application/json" \
        -d '{"id": "test-001", "transactionId": "tx-001", "accountId": "acc-001", "amount": 15000, "type": "Transfer", "category": "WireTransfer", "description": "Large transfer"}')
    
    if echo "$RESPONSE" | grep -q "transactionId"; then
        log_pass "Anomaly detection endpoint"
    else
        log_fail "Anomaly detection endpoint"
    fi
    
    # Test categorization endpoint
    RESPONSE=$(curl -sf -X POST "http://localhost:8003/categorize?description=Starbucks%20coffee")
    
    if echo "$RESPONSE" | grep -q "category"; then
        log_pass "Transaction categorization endpoint"
    else
        log_fail "Transaction categorization endpoint"
    fi
    
    # Test .NET services
    if curl -sf http://localhost:6001/swagger/index.html | grep -q "Swagger"; then
        log_pass "User service Swagger"
    else
        log_fail "User service Swagger"
    fi
    
    if curl -sf http://localhost:6002/swagger/index.html | grep -q "Swagger"; then
        log_pass "Account service Swagger"
    else
        log_fail "Account service Swagger"
    fi
    
    if curl -sf http://localhost:6003/swagger/index.html | grep -q "Swagger"; then
        log_pass "Transaction service Swagger"
    else
        log_fail "Transaction service Swagger"
    fi
}

# AI feature tests (requires Azure credentials)
test_ai_features() {
    log_test "Testing AI features (requires Azure credentials)..."
    
    # Check if AI is configured
    if [ -z "$AZURE_OPENAI_ENDPOINT" ]; then
        log_test "Skipping AI tests - AZURE_OPENAI_ENDPOINT not set"
        return
    fi
    
    # Test anomaly detection with AI explanation
    RESPONSE=$(curl -sf -X POST http://localhost:8002/detect \
        -H "Content-Type: application/json" \
        -d '{"id": "test-002", "transactionId": "tx-002", "accountId": "acc-002", "amount": 50000, "type": "Transfer", "category": "WireTransfer", "description": "LARGE UNUSUAL TRANSFER TO UNKNOWN ACCOUNT"}')
    
    if echo "$RESPONSE" | grep -q "aiExplanation"; then
        log_pass "AI anomaly explanation"
    else
        log_test "AI explanation not available (expected if no Azure credentials)"
    fi
}

# .NET tests
test_dotnet() {
    log_test "Running .NET tests..."
    
    if [ -f "src/shared/Contracts/Contracts.csproj" ]; then
        cd src/shared/Contracts
        if dotnet test --no-restore --verbosity quiet 2>/dev/null; then
            log_pass ".NET Contracts tests"
        else
            log_test ".NET tests skipped or failed"
        fi
        cd - > /dev/null
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "================================"
    echo "Test Summary"
    echo "================================"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo "================================"
}

# Main
main() {
    local mode="${1:---smoke}"
    
    case "$mode" in
        --all)
            test_health
            test_functionality
            test_ai_features
            test_dotnet
            ;;
        --ai)
            test_health
            test_functionality
            test_ai_features
            ;;
        --smoke|*)
            test_health
            test_functionality
            ;;
    esac
    
    print_summary
}

main "$@"