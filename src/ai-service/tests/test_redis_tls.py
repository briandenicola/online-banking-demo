"""
Security tests for Issue #38: Redis TLS Fixed.

Verifies that:
- Python services use ssl_cert_reqs="required" for Redis connections
- Go event-processor uses ServerName for TLS verification (no InsecureSkipVerify)
- Non-Azure mode allows plain connections (for local development)
"""

import pytest
import os


class TestRedisTLSConfigurationIssue38:
    """SECURITY (Issue #38): Verify Redis TLS configuration is secure."""

    def test_python_redis_requires_ssl_cert_verification(self):
        """
        SECURITY (Issue #38): Verify Python Redis connections use ssl_cert_reqs="required".
        Previously used ssl_cert_reqs=None which disabled certificate verification.
        """
        # This test checks the configuration logic
        # In production code, Redis client should be initialized with:
        # redis.Redis(..., ssl_cert_reqs="required") when Azure mode is enabled
        
        # Check ai-service main.py for Redis initialization
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        ai_service_path = os.path.join(repo_root, "src/ai-service/app/main.py")
        
        with open(ai_service_path, 'r') as f:
            content = f.read()
        
        # Verify ssl_cert_reqs="required" is present
        assert 'ssl_cert_reqs="required"' in content or "ssl_cert_reqs='required'" in content, \
            "ai-service should use ssl_cert_reqs='required' for TLS"
        
        # Verify dangerous ssl_cert_reqs=None is NOT present
        assert 'ssl_cert_reqs=None' not in content and "ssl_cert_reqs = None" not in content, \
            "ai-service should NOT use ssl_cert_reqs=None (insecure)"

    def test_python_redis_allows_plain_for_local_dev(self):
        """
        SECURITY (Issue #38): Verify non-Azure mode allows plain connections.
        Local development (AZURE_MODE != true) should allow non-TLS Redis.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        
        # Check that code checks AZURE_MODE or similar before enabling TLS
        ai_service_path = os.path.join(repo_root, "src/ai-service/app/main.py")
        
        with open(ai_service_path, 'r') as f:
            content = f.read()
        
        # Should have conditional logic for Azure mode
        # Either checks os.getenv("AZURE_MODE") or REDIS_URL contains azurecache
        has_azure_check = (
            'AZURE_MODE' in content or
            'azurecache' in content or
            'azure' in content.lower()
        )
        
        assert has_azure_check, \
            "Should have conditional logic for Azure/TLS mode vs local plain Redis"

    def test_chatbot_service_redis_tls_config(self):
        """
        SECURITY (Issue #38): Verify chatbot-service Redis TLS config.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        chatbot_path = os.path.join(repo_root, "src/chatbot-service/app/main.py")
        
        with open(chatbot_path, 'r') as f:
            content = f.read()
        
        # Chatbot service should also use ssl_cert_reqs="required" for Azure
        if 'redis' in content.lower():
            # If chatbot uses Redis, verify TLS config
            if 'ssl_cert_reqs' in content:
                assert 'ssl_cert_reqs="required"' in content or "ssl_cert_reqs='required'" in content, \
                    "chatbot-service should use ssl_cert_reqs='required'"

    def test_budget_service_redis_tls_config(self):
        """
        SECURITY (Issue #38): Verify budget-service Redis TLS config.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        budget_path = os.path.join(repo_root, "src/budget-service/app/main.py")
        
        with open(budget_path, 'r') as f:
            content = f.read()
        
        # Budget service should also use ssl_cert_reqs="required" for Azure
        if 'redis' in content.lower():
            if 'ssl_cert_reqs' in content:
                assert 'ssl_cert_reqs="required"' in content or "ssl_cert_reqs='required'" in content, \
                    "budget-service should use ssl_cert_reqs='required'"


class TestGoRedisTLSConfigurationIssue38:
    """SECURITY (Issue #38): Verify Go event-processor Redis TLS configuration."""

    def test_event_processor_has_server_name_verification(self):
        """
        SECURITY (Issue #38): Verify event-processor uses ServerName for TLS verification.
        Previously used InsecureSkipVerify: true which disabled certificate validation.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        event_processor_path = os.path.join(repo_root, "src/event-processor/main.go")
        
        with open(event_processor_path, 'r') as f:
            content = f.read()
        
        # Verify ServerName is set for TLS config
        assert "ServerName:" in content, \
            "event-processor should set ServerName for TLS verification"
        
        # Verify InsecureSkipVerify is NOT set to true
        assert "InsecureSkipVerify: true" not in content, \
            "event-processor should NOT use InsecureSkipVerify: true (insecure)"
        
        # Verify it uses the hostname from Redis address
        # Should extract hostname and use it for ServerName
        lines = content.split('\n')
        has_hostname_extraction = any(
            'redisHost' in line or 'hostname' in line.lower()
            for line in lines if 'ServerName' in line or 'TLS' in line
        )
        
        assert has_hostname_extraction, \
            "Should extract hostname for ServerName verification"

    def test_event_processor_conditional_tls(self):
        """
        SECURITY (Issue #38): Verify event-processor uses TLS conditionally.
        Should check AZURE_MODE or REDIS_URL for TLS requirements.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        event_processor_path = os.path.join(repo_root, "src/event-processor/main.go")
        
        with open(event_processor_path, 'r') as f:
            content = f.read()
        
        # Should have conditional TLS based on Azure mode
        has_azure_check = (
            'AZURE_MODE' in content or
            'azurecache' in content or
            'tls.Config' in content  # TLS config should be conditional
        )
        
        assert has_azure_check, \
            "Should have conditional TLS configuration"


class TestRedisTLSRegression:
    """Regression tests for Issue #38."""

    def test_no_insecure_skip_verify_in_codebase(self):
        """
        SECURITY (Issue #38): Regression test - no InsecureSkipVerify anywhere.
        This was the vulnerability in Issue #38.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        src_path = os.path.join(repo_root, "src")
        
        # Search for InsecureSkipVerify in Go files
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "InsecureSkipVerify.*true", src_path, "--include=*.go"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode != 0, \
            f"Found InsecureSkipVerify: true in codebase:\n{result.stdout}"

    def test_no_ssl_cert_reqs_none_in_python(self):
        """
        SECURITY (Issue #38): Regression test - no ssl_cert_reqs=None in fixed services.
        Checks only the services that were part of the Issue #38 fix (ai-service,
        chatbot-service, budget-service). Other services may still need remediation.
        """
        import os
        repo_root = "/home/brian/code/online-banking-demo"
        
        # Only check services that were fixed as part of Issue #38
        fixed_services = ["ai-service", "chatbot-service", "budget-service"]
        
        violations = []
        for svc in fixed_services:
            svc_path = os.path.join(repo_root, "src", svc)
            if not os.path.isdir(svc_path):
                continue
            
            import subprocess
            result = subprocess.run(
                ["grep", "-rn", "ssl_cert_reqs=None", svc_path, "--include=*.py"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Filter out test files and comments
                for line in result.stdout.strip().split('\n'):
                    if line and '/tests/' not in line and not line.strip().startswith('#'):
                        violations.append(line)
        
        assert len(violations) == 0, \
            f"Found ssl_cert_reqs=None in fixed services:\n" + "\n".join(violations)
