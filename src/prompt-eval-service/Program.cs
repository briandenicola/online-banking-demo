using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Azure.Cosmos;
using Microsoft.IdentityModel.Tokens;
using Azure.Identity;
using Banking.Observability;
using PromptEvalService.Models;
using PromptEvalService.Repositories;
using PromptEvalService.Services;
var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("prompt-eval-service");

// OpenTelemetry tracing
builder.Services.AddBankingOpenTelemetry("prompt-eval-service");

builder.Services.AddControllers();
builder.Services.AddHttpContextAccessor();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new Microsoft.OpenApi.Models.OpenApiInfo { Title = "Prompt Evaluation Service", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new Microsoft.OpenApi.Models.OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the Bearer scheme",
        Name = "Authorization",
        In = Microsoft.OpenApi.Models.ParameterLocation.Header,
        Type = Microsoft.OpenApi.Models.SecuritySchemeType.Http,
        Scheme = "bearer"
    });
    c.AddSecurityRequirement(new Microsoft.OpenApi.Models.OpenApiSecurityRequirement
    {
        {
            new Microsoft.OpenApi.Models.OpenApiSecurityScheme { Reference = new Microsoft.OpenApi.Models.OpenApiReference { Id = "Bearer", Type = Microsoft.OpenApi.Models.ReferenceType.SecurityScheme } },
            Array.Empty<string>()
        }
    });
});

// JWT Authentication
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

// CORS
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

// HttpClient for ai-service communication
builder.Services.AddHttpClient("AiService", client =>
{
    var aiServiceUrl = builder.Configuration["AI_SERVICE_URL"] ?? "http://ai-service:80";
    client.BaseAddress = new Uri(aiServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(30);
});

// Cosmos DB
builder.Services.AddSingleton<CosmosClient>(sp =>
{
    var configuration = sp.GetRequiredService<IConfiguration>();
    var endpoint = configuration["CosmosDb:Endpoint"];
    if (!string.IsNullOrEmpty(endpoint))
    {
        return new CosmosClient(endpoint, new DefaultAzureCredential());
    }
    return new CosmosClient(configuration["CosmosDb:ConnectionString"]);
});

// Ensure Cosmos containers exist
builder.Services.AddSingleton(async sp =>
{
    var cosmosClient = sp.GetRequiredService<CosmosClient>();
    var config = sp.GetRequiredService<IConfiguration>();
    var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
    var database = cosmosClient.GetDatabase(dbName);

    await database.CreateContainerIfNotExistsAsync(
        config["CosmosDb:TemplatesContainerName"] ?? "PromptTemplates", "/userId");
    await database.CreateContainerIfNotExistsAsync(
        config["CosmosDb:RunsContainerName"] ?? "EvaluationRuns", "/userId");

    return database;
});

// Repositories
builder.Services.AddScoped<IPromptTemplateRepository, CosmosPromptTemplateRepository>();
builder.Services.AddScoped<IEvaluationRunRepository, CosmosEvaluationRunRepository>();

// Background evaluation queue
builder.Services.AddSingleton<EvaluationQueue>();
builder.Services.AddHostedService<EvaluationBackgroundService>();

// Services
builder.Services.AddScoped<IPromptTemplateService, PromptTemplateService>();
builder.Services.AddScoped<IEvaluationService, EvaluationService>();

var app = builder.Build();

// Initialize Cosmos containers
var dbTask = app.Services.GetRequiredService<Task<Database>>();
await dbTask;

// Seed sample prompt templates if none exist
await SeedSampleTemplates(app);

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();
app.UseCorrelationId();
app.UseGlobalExceptionHandler();
app.UseCors();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new { status = "healthy", service = "prompt-eval-service", timestamp = DateTime.UtcNow }));
app.MapGet("/readyz", () => Results.Ok(new { status = "ready" }));

app.Run();

static async Task SeedSampleTemplates(WebApplication app)
{
    using var scope = app.Services.CreateScope();
    var templateService = scope.ServiceProvider.GetRequiredService<IPromptTemplateService>();
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();

    var existing = await templateService.GetAllAsync();
    if (existing.Count > 0) return;

    logger.LogInformation("Seeding sample prompt templates");

    var samples = new[]
    {
        new PromptTemplate
        {
            Id = Guid.NewGuid().ToString(),
            Name = "Risk Scoring — Baseline",
            Description = "Default risk scoring prompt. Evaluates transactions for fraud indicators using amount, merchant, and pattern analysis.",
            Target = "risk-scoring",
            SystemPrompt = @"You are a fraud detection analyst for a retail bank. Analyze the following transaction and assign a risk score between 0.0 (no risk) and 1.0 (certain fraud).

Consider these factors:
- Transaction amount relative to account history
- Merchant category and reputation
- Time of day and geographic patterns
- Velocity (frequency of recent transactions)
- Round-number amounts or just-below-threshold values

Respond with a JSON object:
{
  ""riskScore"": <float 0.0-1.0>,
  ""category"": ""<merchant category>"",
  ""flags"": [""<flag1>"", ""<flag2>""],
  ""explanation"": ""<brief reasoning>""
}",
            Version = 1,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        },
        new PromptTemplate
        {
            Id = Guid.NewGuid().ToString(),
            Name = "Risk Scoring — Conservative",
            Description = "Stricter risk scoring that flags more aggressively. Good for high-value accounts or compliance-heavy environments.",
            Target = "risk-scoring",
            SystemPrompt = @"You are a senior fraud analyst at a bank with zero tolerance for false negatives. Analyze the following transaction and assign a risk score between 0.0 and 1.0.

Apply a conservative approach:
- Any transaction over $500 should start at 0.3 minimum risk
- International transactions add 0.2 to base risk
- Transactions outside business hours (9am-6pm) add 0.1
- Multiple transactions within 1 hour add 0.15 each
- New merchants (first-time) add 0.1

Respond with a JSON object:
{
  ""riskScore"": <float 0.0-1.0>,
  ""category"": ""<merchant category>"",
  ""flags"": [""<flag1>"", ""<flag2>""],
  ""explanation"": ""<brief reasoning>""
}",
            Version = 1,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        },
        new PromptTemplate
        {
            Id = Guid.NewGuid().ToString(),
            Name = "Categorization — Standard",
            Description = "Categorizes transactions into spending categories based on merchant name and description.",
            Target = "categorization",
            SystemPrompt = @"You are a financial categorization engine. Given a transaction with merchant name and description, classify it into exactly one spending category.

Categories: Groceries, Dining, Transportation, Entertainment, Shopping, Utilities, Healthcare, Travel, Education, Subscriptions, Personal Care, Home, Insurance, Gifts, Other

Rules:
- Use the most specific category that fits
- Coffee shops and cafes = Dining
- Gas stations = Transportation
- Streaming services = Subscriptions
- Pharmacies = Healthcare

Respond with a JSON object:
{
  ""category"": ""<category>"",
  ""confidence"": <float 0.0-1.0>,
  ""reasoning"": ""<brief explanation>""
}",
            Version = 1,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        },
        new PromptTemplate
        {
            Id = Guid.NewGuid().ToString(),
            Name = "Categorization — User-Aware",
            Description = "Enhanced categorization that respects user-defined category preferences and custom labels.",
            Target = "categorization",
            SystemPrompt = @"You are a personalized financial categorization engine. Classify the transaction into a spending category, prioritizing the user's custom categories when provided.

Default categories: Groceries, Dining, Transportation, Entertainment, Shopping, Utilities, Healthcare, Travel, Education, Subscriptions, Personal Care, Home, Insurance, Gifts, Other

If user-defined categories are provided, prefer those over defaults when they are a reasonable match. For example, if the user has a ""Coffee"" category, classify Starbucks as ""Coffee"" instead of ""Dining"".

Respond with a JSON object:
{
  ""category"": ""<category>"",
  ""confidence"": <float 0.0-1.0>,
  ""reasoning"": ""<brief explanation>"",
  ""usedCustomCategory"": <true|false>
}",
            Version = 1,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        }
    };

    foreach (var template in samples)
    {
        await templateService.CreateAsync(template);
    }

    logger.LogInformation("Seeded {Count} sample prompt templates", samples.Length);
}
