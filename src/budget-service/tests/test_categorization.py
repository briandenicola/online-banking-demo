"""Tests for budget service categorization and insights endpoints."""


class TestHealthEndpoint:
    def test_health_returns_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestCategorizeEndpoint:
    def test_categorize_returns_category(self, client):
        """Categorize endpoint should return a category for a description."""
        response = client.post("/categorize", params={"description": "coffee at starbucks"})

        assert response.status_code == 200
        data = response.json()
        assert "description" in data
        assert "category" in data
        assert data["description"] == "coffee at starbucks"

    def test_categorize_without_ai_returns_uncategorized(self, client):
        """Without AI client, categorization falls back to Uncategorized."""
        response = client.post("/categorize", params={"description": "random purchase"})

        assert response.status_code == 200
        data = response.json()
        # Without Azure OpenAI configured, should return "Uncategorized"
        assert data["category"] == "Uncategorized"

    def test_categorize_empty_description(self, client):
        """Edge case: empty description string."""
        response = client.post("/categorize", params={"description": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["category"] == "Uncategorized"


class TestInsightsEndpoint:
    def test_insights_for_unknown_user(self, client):
        """Getting insights for a user with no transactions."""
        response = client.get("/insights/unknown-user-id")

        assert response.status_code == 200
        data = response.json()
        assert data["userId"] == "unknown-user-id"
        assert data["totalSpent"] == 0
        assert data["categoryBreakdown"] == {}
        assert "No transactions found for analysis" in data["insights"]

    def test_insights_returns_budget_insight_schema(self, client):
        """Response should match BudgetInsight schema."""
        response = client.get("/insights/test-user")

        assert response.status_code == 200
        data = response.json()
        assert "userId" in data
        assert "period" in data
        assert "totalSpent" in data
        assert "categoryBreakdown" in data
        assert "topCategories" in data
        assert "insights" in data

    def test_insights_with_period_param(self, client):
        """Insights endpoint should accept period parameter."""
        response = client.get("/insights/test-user?period=7d")

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "7d"

    def test_insights_default_period(self, client):
        """Default period should be 30d."""
        response = client.get("/insights/test-user")

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "30d"
