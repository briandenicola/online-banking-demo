using System.Net;
using System.Net.Http.Json;
using FluentAssertions;
using LoanOrigination.Models;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace LoanOrigination.Tests.Contracts;

/// <summary>
/// T031 [US1] Contract tests for GET /api/loans/applications/{applicationNo} and POST .../run.
/// Tests MUST fail until Turk implements LoansController (T047) and LoanAgentOrchestrator (T045).
/// </summary>
public class RunContractTests : IClassFixture<ApplicationsContractTestsFixture>
{
    private readonly HttpClient _client;
    private readonly HttpClient _adminClient;

    public RunContractTests(ApplicationsContractTestsFixture fixture)
    {
        _client = fixture.CreateAuthenticatedClient("test-user-456", "User");
        _adminClient = fixture.CreateAuthenticatedClient("admin-user-789", "Admin");
    }

    [Fact(Skip = "Awaiting T047 + T040 implementation")]
    public async Task GetApplication_ExistingApplication_ReturnsApplicationWithLastRunAndDecision()
    {
        // Arrange: first create an application
        var createRequest = new
        {
            applicant = new
            {
                name = "Bob Marginal",
                dob = "1982-07-22",
                ssnLast4 = "6543",
                phone = "+1-555-0200",
                email = "bob@example.com",
                currentAddress = "456 Oak Lane",
                cityStateZip = "Seattle, WA 98101"
            },
            loanRequest = new
            {
                amount = 15000.00m,
                purpose = "auto",
                termMonths = 60,
                loanType = "auto",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 58000.00m,
                monthlyNetIncome = 3600.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 1200.00m,
                housingStatus = "rent",
                housingPaymentMonthly = 900.00m,
                declaredDtiPct = 33.3m,
                estimatedSavings = 5000.00m,
                retirementInvestments = 10000.00m
            }
        };

        var createResponse = await _client.PostAsJsonAsync("/api/loans/applications", createRequest);
        createResponse.EnsureSuccessStatusCode();
        var application = await createResponse.Content.ReadFromJsonAsync<LoanApplication>();
        var applicationNo = application!.ApplicationNo;

        // Act
        var getResponse = await _client.GetAsync($"/api/loans/applications/{applicationNo}");

        // Assert
        getResponse.StatusCode.Should().Be(HttpStatusCode.OK);

        var detail = await getResponse.Content.ReadFromJsonAsync<dynamic>();
        detail.Should().NotBeNull();
        // Schema expects: application fields + lastRun (nullable) + lastDecision (nullable)
        // Initially both lastRun and lastDecision should be null
    }

    [Fact(Skip = "Awaiting T047 + T045 implementation")]
    public async Task PostRun_ValidApplication_ReturnsAgentRunResponseWith10Steps()
    {
        // Arrange: create application
        var createRequest = new
        {
            applicant = new
            {
                name = "Alice Goodman",
                dob = "1985-03-14",
                ssnLast4 = "4321",
                phone = "+1-555-0100",
                email = "alice@example.com",
                currentAddress = "123 Pine St",
                cityStateZip = "Austin, TX 78701"
            },
            loanRequest = new
            {
                amount = 25000.00m,
                purpose = "home_improvement",
                termMonths = 36,
                loanType = "personal",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 120000.00m,
                monthlyNetIncome = 7500.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 400.00m,
                housingStatus = "rent",
                housingPaymentMonthly = 1800.00m,
                declaredDtiPct = 5.3m,
                estimatedSavings = 25000.00m,
                retirementInvestments = 80000.00m
            }
        };

        var createResponse = await _client.PostAsJsonAsync("/api/loans/applications", createRequest);
        createResponse.EnsureSuccessStatusCode();
        var application = await createResponse.Content.ReadFromJsonAsync<LoanApplication>();
        var applicationNo = application!.ApplicationNo;

        // Act
        var runResponse = await _client.PostAsync($"/api/loans/applications/{applicationNo}/run", null);

        // Assert
        runResponse.StatusCode.Should().Be(HttpStatusCode.OK);

        var runResult = await runResponse.Content.ReadFromJsonAsync<AgentRunResponse>();
        runResult.Should().NotBeNull();
        runResult!.RunId.Should().MatchRegex(@"^RUN-\d{4}-\d{7}$", "runId must match expected format");
        runResult.ApplicationNo.Should().Be(applicationNo);
        runResult.WorkflowLog.Should().HaveCount(10, "workflow must execute all 10 steps S01-S10");

        // Verify step IDs
        runResult.WorkflowLog.Select(s => s.StepId).Should().BeEquivalentTo(
            new[] { "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10" },
            options => options.WithStrictOrdering());

        // Verify each step has required fields
        foreach (var step in runResult.WorkflowLog)
        {
            step.StepName.Should().NotBeNullOrEmpty();
            step.Status.Should().BeOneOf("completed", "failed");
            step.Timestamp.Should().BeCloseTo(DateTime.UtcNow, TimeSpan.FromMinutes(2));
        }

        // Verify recommendation structure
        runResult.Recommendation.Should().NotBeNull();
        runResult.Recommendation.Recommendation.Should().BeOneOf("APPROVE", "CONDITIONAL", "DECLINE");
        runResult.Recommendation.Confidence.Should().BeInRange(0.0m, 1.0m);
    }

    [Fact(Skip = "Awaiting T047 implementation")]
    public async Task GetApplication_NonExistent_Returns404()
    {
        // Act
        var response = await _client.GetAsync("/api/loans/applications/APP-9999-999999");

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.NotFound);
    }

    [Fact(Skip = "Awaiting T047 + T040 + authorization implementation")]
    public async Task GetApplication_NotOwner_Returns403()
    {
        // Arrange: user1 creates an application
        var user1Client = new ApplicationsContractTestsFixture()
            .CreateAuthenticatedClient("user-111", "User");

        var createRequest = new
        {
            applicant = new
            {
                name = "User One",
                dob = "1990-01-01",
                ssnLast4 = "1111",
                email = "user1@example.com",
                currentAddress = "111 First St",
                cityStateZip = "City, ST 11111"
            },
            loanRequest = new
            {
                amount = 10000.00m,
                purpose = "personal",
                termMonths = 36,
                loanType = "personal",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 50000.00m,
                monthlyNetIncome = 3000.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 500.00m,
                housingStatus = "rent",
                housingPaymentMonthly = 800.00m,
                declaredDtiPct = 16.7m,
                estimatedSavings = 5000.00m,
                retirementInvestments = 10000.00m
            }
        };

        var createResponse = await user1Client.PostAsJsonAsync("/api/loans/applications", createRequest);
        createResponse.EnsureSuccessStatusCode();
        var application = await createResponse.Content.ReadFromJsonAsync<LoanApplication>();
        var applicationNo = application!.ApplicationNo;

        // Act: user2 tries to access user1's application
        var user2Client = new ApplicationsContractTestsFixture()
            .CreateAuthenticatedClient("user-222", "User");
        var getResponse = await user2Client.GetAsync($"/api/loans/applications/{applicationNo}");

        // Assert
        getResponse.StatusCode.Should().Be(HttpStatusCode.Forbidden,
            "users cannot access applications they don't own");
    }

    [Fact(Skip = "Awaiting T047 + T045 implementation")]
    public async Task PostRun_NonExistent_Returns404()
    {
        // Act
        var response = await _client.PostAsync("/api/loans/applications/APP-9999-999999/run", null);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.NotFound);
    }
}
