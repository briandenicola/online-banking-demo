using System.Net;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using FluentAssertions;
using LoanOrigination.Models;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace LoanOrigination.Tests.Contracts;

/// <summary>
/// T030 [US1] Contract tests for POST /api/loans/applications against OpenAPI schema.
/// Tests MUST fail until Turk implements LoansController (T047).
/// </summary>
public class ApplicationsContractTests : IClassFixture<ApplicationsContractTestsFixture>
{
    private readonly HttpClient _client;

    public ApplicationsContractTests(ApplicationsContractTestsFixture fixture)
    {
        _client = fixture.CreateAuthenticatedClient("test-user-123", "User");
    }

    [Fact]
    public async Task PostApplications_ValidRequest_Returns201WithApplicationNo()
    {
        // Arrange
        var request = new
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

        // Act
        var response = await _client.PostAsJsonAsync("/api/loans/applications", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.Created);
        response.Headers.Location.Should().NotBeNull("Location header must be present per OpenAPI spec");

        var application = await response.Content.ReadFromJsonAsync<LoanApplication>();
        application.Should().NotBeNull();
        application!.ApplicationNo.Should().MatchRegex(@"^APP-\d{4}-\d{6}$", "applicationNo must match format");
        application.UserId.Should().Be("test-user-123", "userId must be extracted from JWT, never from body");
        application.Status.Should().Be("submitted");
        application.LoanRequest.Amount.Should().Be(25000.00m);
        application.LoanRequest.TermMonths.Should().Be(36);
        application.LoanRequest.LoanType.Should().Be("personal");
        application.Applicant.Name.Should().Be("Alice Goodman");
        application.CreatedAt.Should().BeCloseTo(DateTime.UtcNow, TimeSpan.FromMinutes(1));
    }

    [Fact]
    public async Task PostApplications_InvalidLoanType_Returns400()
    {
        // Arrange
        var request = new
        {
            applicant = new
            {
                name = "Bob Test",
                dob = "1990-01-01",
                ssnLast4 = "1234",
                email = "bob@example.com",
                currentAddress = "456 Oak St",
                cityStateZip = "Seattle, WA 98101"
            },
            loanRequest = new
            {
                amount = 15000.00m,
                purpose = "other",
                termMonths = 60,
                loanType = "invalid_type", // Invalid
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

        // Act
        var response = await _client.PostAsJsonAsync("/api/loans/applications", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.BadRequest,
            "invalid loanType should be rejected per validation rules");
    }

    [Fact]
    public async Task PostApplications_AmountBelowMinimum_Returns400()
    {
        // Arrange
        var request = new
        {
            applicant = new
            {
                name = "Charlie Test",
                dob = "1992-05-20",
                ssnLast4 = "9876",
                email = "charlie@example.com",
                currentAddress = "789 Elm St",
                cityStateZip = "Portland, OR 97201"
            },
            loanRequest = new
            {
                amount = 500.00m, // Below $1,000 minimum
                purpose = "personal",
                termMonths = 24,
                loanType = "personal",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 42000.00m,
                monthlyNetIncome = 2600.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 800.00m,
                housingStatus = "rent",
                housingPaymentMonthly = 700.00m,
                declaredDtiPct = 30.8m,
                estimatedSavings = 2000.00m,
                retirementInvestments = 5000.00m
            }
        };

        // Act
        var response = await _client.PostAsJsonAsync("/api/loans/applications", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.BadRequest,
            "amount below $1,000 minimum should be rejected per validation rules");
    }

    [Fact]
    public async Task PostApplications_InvalidTermMonths_Returns400()
    {
        // Arrange
        var request = new
        {
            applicant = new
            {
                name = "Dana Test",
                dob = "1988-08-15",
                ssnLast4 = "5555",
                email = "dana@example.com",
                currentAddress = "321 Maple Ave",
                cityStateZip = "Denver, CO 80202"
            },
            loanRequest = new
            {
                amount = 10000.00m,
                purpose = "debt_consolidation",
                termMonths = 37, // Not in allowed list
                loanType = "personal",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 75000.00m,
                monthlyNetIncome = 4500.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 600.00m,
                housingStatus = "own",
                housingPaymentMonthly = 0.00m,
                declaredDtiPct = 13.3m,
                estimatedSavings = 15000.00m,
                retirementInvestments = 40000.00m
            }
        };

        // Act
        var response = await _client.PostAsJsonAsync("/api/loans/applications", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.BadRequest,
            "termMonths not in allowed set [12,24,36,48,60,72,84,120,180,240,360] should be rejected");
    }

    [Fact(Skip = "Awaiting T047 implementation")]
    public async Task PostApplications_WithoutAuthToken_Returns401()
    {
        // Arrange
        var unauthenticatedClient = new ApplicationsContractTestsFixture().CreateUnauthenticatedClient();
        var request = new
        {
            applicant = new
            {
                name = "Eve Test",
                dob = "1995-12-01",
                ssnLast4 = "7777",
                email = "eve@example.com",
                currentAddress = "999 Broadway",
                cityStateZip = "New York, NY 10001"
            },
            loanRequest = new
            {
                amount = 20000.00m,
                purpose = "auto",
                termMonths = 60,
                loanType = "auto",
                paymentMethod = "AUTO_DEBIT"
            },
            financials = new
            {
                grossAnnualIncome = 65000.00m,
                monthlyNetIncome = 4000.00m,
                otherIncomeMonthly = 0.00m,
                totalMonthlyDebtPayments = 500.00m,
                housingStatus = "rent",
                housingPaymentMonthly = 1200.00m,
                declaredDtiPct = 12.5m,
                estimatedSavings = 10000.00m,
                retirementInvestments = 25000.00m
            }
        };

        // Act
        var response = await unauthenticatedClient.PostAsJsonAsync("/api/loans/applications", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized,
            "requests without valid JWT should be rejected");
    }
}

public class ApplicationsContractTestsFixture : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureTestServices(services =>
        {
            // Register test authentication handler
            services.AddAuthentication("Test")
                .AddScheme<AuthenticationSchemeOptions, TestAuthHandler>("Test", options => { });
        });

        builder.UseEnvironment("Testing");
    }

    public HttpClient CreateAuthenticatedClient(string userId, string role)
    {
        var client = CreateClient();
        client.DefaultRequestHeaders.Add("X-Test-UserId", userId);
        client.DefaultRequestHeaders.Add("X-Test-Role", role);
        return client;
    }

    public HttpClient CreateUnauthenticatedClient()
    {
        return CreateClient();
    }
}

public class TestAuthHandler : AuthenticationHandler<AuthenticationSchemeOptions>
{
    public TestAuthHandler(
        Microsoft.Extensions.Options.IOptionsMonitor<AuthenticationSchemeOptions> options,
        Microsoft.Extensions.Logging.ILoggerFactory logger,
        System.Text.Encodings.Web.UrlEncoder encoder)
        : base(options, logger, encoder)
    {
    }

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (!Request.Headers.ContainsKey("X-Test-UserId"))
        {
            return Task.FromResult(AuthenticateResult.NoResult());
        }

        var userId = Request.Headers["X-Test-UserId"].ToString();
        var role = Request.Headers["X-Test-Role"].ToString();

        var claims = new List<Claim>
        {
            new Claim("userId", userId),
            new Claim(ClaimTypes.Role, role)
        };

        var identity = new ClaimsIdentity(claims, "Test");
        var principal = new ClaimsPrincipal(identity);
        var ticket = new AuthenticationTicket(principal, "Test");

        return Task.FromResult(AuthenticateResult.Success(ticket));
    }
}
