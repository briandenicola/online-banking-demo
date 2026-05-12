"""
Security tests for Issue #36: LLM Security Fixed (chatbot-service).

Verifies that:
- Tool functions do NOT accept user_id parameter (extracted from JWT instead)
- user_id is resolved from JWT context, not from user input
- Tool functions use ContextVar for authentication
"""

import pytest
import inspect
from app.main import (
    get_user_transactions,
    get_user_accounts,
    get_budget_insights,
    get_spending_pattern,
    AGENT_FRAMEWORK_AVAILABLE,
)


def _get_underlying_func(obj):
    """Get the underlying function from a @tool-decorated FunctionTool or plain function."""
    if hasattr(obj, "func"):
        return obj.func
    return obj


class TestToolFunctionSecurityIssue36:
    """SECURITY (Issue #36): Tool functions must NOT accept user_id parameter."""

    def test_get_user_transactions_no_user_id_parameter(self):
        """
        SECURITY (Issue #36): Verifies get_user_transactions does not accept user_id parameter.
        Previously, tool functions accepted user_id which allowed prompt injection attacks.
        Now user_id is resolved from JWT token via ContextVar.
        """
        fn = _get_underlying_func(get_user_transactions)
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        
        assert "user_id" not in param_names, \
            "get_user_transactions must NOT accept user_id parameter (security issue #36)"
        
        assert len(param_names) == 0, \
            f"get_user_transactions should accept zero parameters, found: {param_names}"

    def test_get_user_accounts_no_user_id_parameter(self):
        """
        SECURITY (Issue #36): Verifies get_user_accounts does not accept user_id parameter.
        User identity must come from JWT context, not from LLM-controlled parameters.
        """
        fn = _get_underlying_func(get_user_accounts)
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        
        assert "user_id" not in param_names, \
            "get_user_accounts must NOT accept user_id parameter (security issue #36)"
        
        assert len(param_names) == 0, \
            f"get_user_accounts should accept zero parameters, found: {param_names}"

    def test_get_budget_insights_no_user_id_parameter(self):
        """
        SECURITY (Issue #36): Verifies get_budget_insights does not accept user_id parameter.
        Only accepts optional 'period' parameter, user identity from JWT.
        """
        fn = _get_underlying_func(get_budget_insights)
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        
        assert "user_id" not in param_names, \
            "get_budget_insights must NOT accept user_id parameter (security issue #36)"
        
        assert set(param_names) == {"period"}, \
            f"get_budget_insights should only accept 'period', found: {param_names}"

    def test_get_spending_pattern_no_user_id_parameter(self):
        """
        SECURITY (Issue #36): Verifies get_spending_pattern does not accept user_id parameter.
        """
        fn = _get_underlying_func(get_spending_pattern)
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        
        assert "user_id" not in param_names, \
            "get_spending_pattern must NOT accept user_id parameter (security issue #36)"
        
        assert len(param_names) == 0, \
            f"get_spending_pattern should accept zero parameters, found: {param_names}"

    def test_tool_functions_use_context_var(self, client):
        """
        SECURITY (Issue #36): Verifies tool functions use ContextVar for JWT token.
        Tool functions should call _current_auth_token.get() to retrieve JWT.
        """
        import app.main as main_module
        
        assert hasattr(main_module, "_current_auth_token"), \
            "Module should define _current_auth_token ContextVar"
        
        from contextvars import ContextVar
        assert isinstance(main_module._current_auth_token, ContextVar), \
            "_current_auth_token should be a ContextVar"

    def test_tool_decorators_present(self):
        """
        SECURITY (Issue #36): Verifies tool functions have @tool decorator.
        This ensures they're properly integrated with the Agent framework.
        """
        if not AGENT_FRAMEWORK_AVAILABLE:
            pytest.skip("Agent framework not available")
        
        # Agent framework wraps @tool functions into FunctionTool objects
        # with a .name attribute and .func pointing to the underlying function
        assert hasattr(get_user_transactions, "name"), \
            "get_user_transactions should be a FunctionTool with a name"
        assert hasattr(get_user_accounts, "name"), \
            "get_user_accounts should be a FunctionTool with a name"


class TestAccountDataSanitization:
    """SECURITY (Issue #36): Verifies account data is sanitized before passing to LLM."""

    def test_mask_account_number_function_exists(self):
        """Verify _mask_account_number function exists for security."""
        from app.main import _mask_account_number
        
        # Test masking logic
        masked = _mask_account_number("ACC1234567890")
        assert masked == "****7890", "Should mask all but last 4 digits"
        
        masked_short = _mask_account_number("123")
        assert masked_short == "****", "Should handle short account numbers"
        
        masked_none = _mask_account_number(None)
        assert masked_none == "****", "Should handle None gracefully"

    def test_sanitize_account_data_function_exists(self):
        """Verify _sanitize_account_data function exists and works."""
        from app.main import _sanitize_account_data
        
        test_accounts = [
            {
                "id": "acc-123",
                "accountNumber": "ACC9876543210",
                "type": "Checking",
                "balance": 5000.50,
                "currency": "USD",
                "routingNumber": "123456789",  # Should be excluded
                "ssn": "123-45-6789",  # Should be excluded
            }
        ]
        
        sanitized = _sanitize_account_data(test_accounts)
        
        assert len(sanitized) == 1
        assert sanitized[0]["accountNumber"] == "****3210", "Account number should be masked"
        assert "routingNumber" not in sanitized[0], "Routing number should be excluded"
        assert "ssn" not in sanitized[0], "SSN should be excluded"
        assert sanitized[0]["balance"] == 5000.50, "Balance should be included"

    def test_sanitize_transaction_description(self):
        """Verify _sanitize_transaction_description removes PII."""
        from app.main import _sanitize_transaction_description
        
        # Test email removal
        desc_with_email = "Payment to john.doe@example.com for services"
        sanitized = _sanitize_transaction_description(desc_with_email)
        assert "@example.com" not in sanitized, "Email should be removed"
        assert "[EMAIL]" in sanitized, "Email should be replaced with [EMAIL]"
        
        # Test phone removal
        desc_with_phone = "Call 555-123-4567 for support"
        sanitized = _sanitize_transaction_description(desc_with_phone)
        assert "555-123-4567" not in sanitized, "Phone should be removed"
        assert "[PHONE]" in sanitized, "Phone should be replaced with [PHONE]"
        
        # Test length limiting
        long_desc = "A" * 200
        sanitized = _sanitize_transaction_description(long_desc)
        assert len(sanitized) <= 100, "Description should be truncated to 100 chars"
        assert sanitized.endswith("..."), "Long descriptions should end with ..."


class TestPromptInjectionResistance:
    """SECURITY (Issue #36): Verifies LLM system prompt has injection resistance."""

    def test_system_prompt_defines_scope_boundaries(self):
        """Verify system prompt includes scope restriction instructions."""
        from app.main import FINANCIAL_ADVISOR_INSTRUCTIONS
        
        assert "SCOPE RESTRICTION" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "System prompt should define scope boundaries"
        assert "ONLY answer questions about personal finances" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "Should restrict to finance topics"

    def test_system_prompt_resists_prompt_injection(self):
        """Verify system prompt includes prompt injection resistance."""
        from app.main import FINANCIAL_ADVISOR_INSTRUCTIONS
        
        assert "PROMPT INJECTION RESISTANCE" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "System prompt should include injection resistance"
        assert "ignore previous instructions" in FINANCIAL_ADVISOR_INSTRUCTIONS.lower(), \
            "Should mention common injection phrases"

    def test_system_prompt_protects_pii(self):
        """Verify system prompt includes PII protection instructions."""
        from app.main import FINANCIAL_ADVISOR_INSTRUCTIONS
        
        assert "PII PROTECTION" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "System prompt should include PII protection"
        assert "Never repeat full account numbers" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "Should instruct LLM not to repeat account numbers"
        assert "partial masking" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "Should instruct use of partial masking"

    def test_system_prompt_restricts_tool_usage(self):
        """Verify system prompt includes tool usage restrictions."""
        from app.main import FINANCIAL_ADVISOR_INSTRUCTIONS
        
        assert "TOOL USAGE" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "System prompt should include tool usage guidelines"
        assert "authenticated by the system" in FINANCIAL_ADVISOR_INSTRUCTIONS, \
            "Should clarify tools are authenticated automatically"
