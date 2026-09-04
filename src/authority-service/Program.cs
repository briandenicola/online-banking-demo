using System.Text;
using Azure.Identity;
using Banking.Observability;
using AuthorityService;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Azure.Cosmos;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);

builder.Host.UseBankingSerilog("authority-service");
builder.Services.AddBankingOpenTelemetry("authority-service");

builder.Services.AddControllers()
    .AddNewtonsoftJson();

builder.Services.AddHttpContextAccessor();
builder.Services.AddHttpClient();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Authority Service", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the bearer scheme",
        Name = "Authorization",
        In = ParameterLocation.Header,
        Type = SecuritySchemeType.Http,
        Scheme = "bearer"
    });
    c.AddSecurityRequirement(doc => new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecuritySchemeReference("Bearer", doc),
            []
        }
    });
});

builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(options =>
{
    options.UseSecurityTokenValidators = true;
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = builder.Configuration["Jwt:Issuer"],
        ValidAudience = builder.Configuration["Jwt:Audience"],
        IssuerSigningKey = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"]!))
    };
});

builder.Services.AddAuthorization();

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.WithOrigins("http://localhost:3000", "http://localhost")
              .AllowAnyMethod()
              .AllowAnyHeader()
              .AllowCredentials();
    });
});

// ---------------------------------------------------------------------------------------
// POLICY — loaded once, at startup, BEFORE anything can serve a request.
//
// Fail closed: a missing or invalid policy file terminates startup. There is no default
// ladder and no code-level fallback threshold. A service that cannot read its policy has no
// business deciding who may sign what.
// ---------------------------------------------------------------------------------------
var policyPath = builder.Configuration["POLICY_FILE_PATH"]
                 ?? builder.Configuration["Policy:FilePath"];

var resolvedPolicy = PolicyLoader.FromConfiguration(builder.Configuration).LoadFromFile(policyPath!);

builder.Services.AddSingleton<IPolicyProvider>(_ => new PolicyProvider(resolvedPolicy));
builder.Services.AddSingleton<IPolicyEvaluator, PolicyEvaluator>();
builder.Services.AddSingleton<ISignatureService, HmacSignatureService>();
builder.Services.AddSingleton<IDenialReasonValidator, DenialReasonValidator>();
builder.Services.AddSingleton<ActorContextFactory>();

var useInMemory = builder.Configuration.GetValue("UseInMemoryDatabase", false);

if (useInMemory)
{
    // Local/compose mode. Single instance so the store survives across requests.
    builder.Services.AddSingleton<IApprovalRepository, InMemoryApprovalRepository>();
}
else
{
    builder.Services.AddSingleton<CosmosClient>(sp =>
    {
        var configuration = sp.GetRequiredService<IConfiguration>();
        var endpoint = configuration["CosmosDb:Endpoint"];

        // Explicit, not inherited: the document shape is a ratified contract (design §5.3.1b)
        // and a Cosmos path mismatch returns zero rows rather than an error. `SerializerOptions`
        // is deliberately NOT used — it would layer a naming policy over the [JsonProperty]
        // attributes and drop null fields, both of which change field paths invisibly.
        var clientOptions = new CosmosClientOptions
        {
            Serializer = new AuthorityService.Models.ApprovalCosmosSerializer()
        };

        // Dual mode: an endpoint means Entra RBAC via DefaultAzureCredential (AZURE_CLIENT_ID
        // selects the user-assigned identity); otherwise the local emulator connection string.
        if (!string.IsNullOrEmpty(endpoint))
        {
            return new CosmosClient(endpoint, new DefaultAzureCredential(), clientOptions);
        }

        return new CosmosClient(configuration["CosmosDb:ConnectionString"], clientOptions);
    });

    builder.Services.AddSingleton(async sp =>
    {
        var cosmosClient = sp.GetRequiredService<CosmosClient>();
        var config = sp.GetRequiredService<IConfiguration>();
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var database = cosmosClient.GetDatabase(dbName);

        await database.CreateContainerIfNotExistsAsync(
            new ContainerProperties(
                config["CosmosDb:ApprovalsContainerName"] ?? "copilot-approvals",
                "/" + SharedIdentifiers.Fields.RequesterId)
            {
                // -1, not a positive value: TTL must never be the expiry mechanism. The ttl
                // field is set per-document only once an approval is terminal.
                DefaultTimeToLive = -1
            });

        return database;
    });

    builder.Services.AddSingleton<IApprovalRepository, CosmosApprovalRepository>();
}

// Redis — dual mode, matching the pattern the other services use.
var redisConnectionString = builder.Configuration["Redis:ConnectionString"];

if (!string.IsNullOrWhiteSpace(redisConnectionString))
{
    builder.Services.AddSingleton<IConnectionMultiplexer>(sp =>
    {
        var options = ConfigurationOptions.Parse(redisConnectionString);
        options.AbortOnConnectFail = false;

        var clientId = builder.Configuration["AZURE_CLIENT_ID"];

        if (!string.IsNullOrWhiteSpace(clientId))
        {
            // Azure Managed Redis: Entra auth, TLS, port 10000.
            options.ConfigureForAzureWithTokenCredentialAsync(
                new DefaultAzureCredential(
                    new DefaultAzureCredentialOptions { ManagedIdentityClientId = clientId }))
                .GetAwaiter().GetResult();
        }

        return ConnectionMultiplexer.Connect(options);
    });

    builder.Services.AddSingleton<IAuditPublisher, RedisAuditPublisher>();
}
else
{
    builder.Services.AddSingleton<IAuditPublisher, NullAuditPublisher>();
}

builder.Services.AddSingleton<IActionBroker, HttpActionBroker>();
builder.Services.AddScoped<ApprovalService>();
builder.Services.AddHostedService<ExpirySweeperBackgroundService>();

var app = builder.Build();

if (!useInMemory)
{
    await app.Services.GetRequiredService<Task<Database>>();
}

app.Logger.LogInformation(
    "Authority policy {PolicyId} loaded; policyVersion {PolicyVersion} ({Thresholds} thresholds, " +
    "{Actions} action types)",
    resolvedPolicy.PolicyId, resolvedPolicy.PolicyVersion,
    resolvedPolicy.Thresholds.Count, resolvedPolicy.Document.ActionTypes.Count);

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseCorrelationId();
app.UseGlobalExceptionHandler();
app.UseMiddleware<AuthorityService.Middleware.AuthorityExceptionMiddleware>();
app.UseCors();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new
{
    status = "healthy",
    service = "authority-service",
    timestamp = DateTime.UtcNow
}));

app.MapGet("/readyz", (IPolicyProvider policies) => Results.Ok(new
{
    status = "ready",
    policyId = policies.Current.PolicyId,
    policyVersion = policies.Current.PolicyVersion
}));

app.Run();

/// <summary>Exposed so the test host can reference this assembly's entry point.</summary>
public partial class Program;
