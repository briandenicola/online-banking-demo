# Skill: Contract Testing with WebApplicationFactory

**Type**: Testing Pattern  
**Languages**: C# / .NET  
**Dependencies**: ASP.NET Core, xUnit, Microsoft.AspNetCore.Mvc.Testing  
**Maintainer**: Livingston (Tester/QA)

---

## Overview

A reusable pattern for writing contract tests (integration tests) for ASP.NET Core APIs using `WebApplicationFactory<T>`. Validates the full HTTP stack (routing, authentication, model binding, validation, serialization) without external service dependencies.

---

## When to Use

- Testing REST API endpoints against OpenAPI schema contracts
- Validating JWT authentication/authorization flows without real tokens
- Testing model validation and error responses (400, 401, 403, 404)
- Integration testing without spinning up external services (Cosmos, Redis, Foundry)

---

## Pattern

### 1. Create a Test Fixture

```csharp
public class MyApiTestsFixture : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureTestServices(services =>
        {
            // Override services for testing (e.g., use in-memory repos)
            services.AddSingleton<IMyRepository, FakeMyRepository>();
            
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
```

### 2. Create a Test Auth Handler

```csharp
public class TestAuthHandler : AuthenticationHandler<AuthenticationSchemeOptions>
{
    public TestAuthHandler(
        IOptionsMonitor<AuthenticationSchemeOptions> options,
        ILoggerFactory logger,
        UrlEncoder encoder)
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
```

### 3. Write Contract Tests

```csharp
public class MyApiContractTests : IClassFixture<MyApiTestsFixture>
{
    private readonly HttpClient _client;

    public MyApiContractTests(MyApiTestsFixture fixture)
    {
        _client = fixture.CreateAuthenticatedClient("test-user-123", "User");
    }

    [Fact]
    public async Task PostResource_ValidRequest_Returns201WithLocation()
    {
        // Arrange
        var request = new { name = "Test", value = 42 };

        // Act
        var response = await _client.PostAsJsonAsync("/api/resources", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.Created);
        response.Headers.Location.Should().NotBeNull();
        
        var result = await response.Content.ReadFromJsonAsync<MyResource>();
        result.Should().NotBeNull();
        result!.Id.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task PostResource_InvalidRequest_Returns400()
    {
        // Arrange
        var request = new { name = "", value = -1 }; // Invalid

        // Act
        var response = await _client.PostAsJsonAsync("/api/resources", request);

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task GetResource_WithoutAuth_Returns401()
    {
        // Arrange
        var unauthClient = new MyApiTestsFixture().CreateUnauthenticatedClient();

        // Act
        var response = await unauthClient.GetAsync("/api/resources/123");

        // Assert
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }
}
```

---

## Key Benefits

1. **Full HTTP stack testing** — Validates routing, auth, serialization, validation in one test
2. **No real JWTs needed** — TestAuthHandler injects claims via headers (simpler, faster)
3. **No external services** — Tests run in-memory, ideal for CI/CD
4. **OpenAPI compliance** — Assert response codes, headers, and body shapes match spec
5. **Parallel-safe** — Each test gets its own `HttpClient` instance

---

## Common Patterns

### Testing Authorization

```csharp
[Fact]
public async Task AdminEndpoint_NonAdminUser_Returns403()
{
    var userClient = fixture.CreateAuthenticatedClient("user-123", "User");
    var response = await userClient.GetAsync("/api/admin/dashboard");
    response.StatusCode.Should().Be(HttpStatusCode.Forbidden);
}
```

### Testing Ownership

```csharp
[Fact]
public async Task GetResource_NotOwner_Returns403()
{
    // User1 creates a resource
    var user1Client = fixture.CreateAuthenticatedClient("user-1", "User");
    var createResponse = await user1Client.PostAsJsonAsync("/api/resources", new { name = "Test" });
    var resource = await createResponse.Content.ReadFromJsonAsync<MyResource>();

    // User2 tries to access it
    var user2Client = fixture.CreateAuthenticatedClient("user-2", "User");
    var getResponse = await user2Client.GetAsync($"/api/resources/{resource!.Id}");
    
    getResponse.StatusCode.Should().Be(HttpStatusCode.Forbidden);
}
```

### Testing Model Validation

```csharp
[Theory]
[InlineData("", "empty name should fail")]
[InlineData("a", "too short should fail")]
[InlineData("x" * 201, "too long should fail")]
public async Task PostResource_InvalidName_Returns400(string invalidName, string because)
{
    var response = await _client.PostAsJsonAsync("/api/resources", new { name = invalidName });
    response.StatusCode.Should().Be(HttpStatusCode.BadRequest, because);
}
```

---

## Anti-Patterns to Avoid

❌ **Don't generate real JWTs in tests** — Use TestAuthHandler instead  
❌ **Don't test business logic here** — That's for unit tests; contract tests validate HTTP behavior  
❌ **Don't hardcode IDs** — Generate them dynamically or use factories  
❌ **Don't share state between tests** — Each test should be independent

---

## References

- **Used in**: `src/loan-origination-service.Tests/Contracts/ApplicationsContractTests.cs` (T030)
- **Pattern origin**: `src/account-service.Tests/AccountsControllerTests.cs`
- **Microsoft Docs**: [Integration tests in ASP.NET Core](https://learn.microsoft.com/en-us/aspnet/core/test/integration-tests)

---

## Related Skills

- `unit-testing-moq` — Mocking dependencies in unit tests
- `deterministic-enrichment` — Reproducible synthetic data generation
- `openapi-contract-validation` — Asserting API responses match OpenAPI schemas
