using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Azure.Cosmos;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using Azure.Identity;
using StackExchange.Redis;
using Banking.Observability;
using LoanOrigination.Agents;
using LoanOrigination.Repositories;
using LoanOrigination.Services;
using Newtonsoft.Json;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("loan-origination-service");

// OpenTelemetry tracing with workflow activity source
builder.Services.AddBankingOpenTelemetry("loan-origination-service");

builder.Services.AddControllers()
    .AddNewtonsoftJson(options =>
    {
        options.SerializerSettings.NullValueHandling = NullValueHandling.Ignore;
        options.SerializerSettings.Converters.Add(new Newtonsoft.Json.Converters.StringEnumConverter());
    });

builder.Services.AddHttpContextAccessor();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Loan Origination Service", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the Bearer scheme",
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

// JWT Authentication
builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(options =>
{
    var jwtKey = builder.Configuration["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key is not configured");
    var jwtIssuer = builder.Configuration["Jwt:Issuer"] ?? "user-service";
    var jwtAudience = builder.Configuration["Jwt:Audience"] ?? "banking-demo";

    options.UseSecurityTokenValidators = true;
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = jwtIssuer,
        ValidAudience = jwtAudience,
        IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtKey))
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

// HttpClient for user-service lookup
builder.Services.AddHttpClient("UserService", client =>
{
    var userServiceUrl = builder.Configuration["UserService:Url"] ?? "http://user-service:80";
    client.BaseAddress = new Uri(userServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(10);
});

// Redis connection multiplexer with Entra auth
builder.Services.AddSingleton<IConnectionMultiplexer>(sp =>
{
    var connectionString = sp.GetRequiredService<IConfiguration>()["Redis:ConnectionString"] ?? "redis:6379";
    var configOptions = ConfigurationOptions.Parse(connectionString);
    if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AZURE_CLIENT_ID")))
    {
        var credential = new DefaultAzureCredential();
        configOptions.ConfigureForAzureWithTokenCredentialAsync(credential).GetAwaiter().GetResult();
    }
    return ConnectionMultiplexer.Connect(configOptions);
});

// Use in-memory mode for local development if configured
var useInMemory = builder.Configuration.GetValue<bool>("UseInMemoryDatabase", false);

if (!useInMemory)
{
    // Cosmos DB with Newtonsoft serializer
    builder.Services.AddSingleton<CosmosClient>(sp =>
    {
        var configuration = sp.GetRequiredService<IConfiguration>();
        var endpoint = configuration["CosmosDb:Endpoint"];
        
        var clientOptions = new CosmosClientOptions
        {
            SerializerOptions = new CosmosSerializationOptions
            {
                PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase,
                IgnoreNullValues = true
            }
        };
        
        if (!string.IsNullOrEmpty(endpoint) && Uri.IsWellFormedUriString(endpoint, UriKind.Absolute))
        {
            return new CosmosClient(endpoint, new DefaultAzureCredential(), clientOptions);
        }
        else if (!string.IsNullOrEmpty(endpoint))
        {
            throw new InvalidOperationException($"CosmosDb:Endpoint is set but is not a valid URI: '{endpoint}'");
        }
        return new CosmosClient(configuration["CosmosDb:ConnectionString"], clientOptions);
    });

    // Repositories
    builder.Services.AddScoped<ICosmosPolicyRepository, CosmosPolicyRepository>();

    // Services
    builder.Services.AddScoped<IUserLookupService, UserLookupService>();
}

// Prompt loader
builder.Services.AddSingleton<PromptLoader>();

// Agent registration hosted service
builder.Services.AddHostedService<AgentRegistration>();

var app = builder.Build();

// Load prompts before agent registration
if (!useInMemory)
{
    var promptLoader = app.Services.GetRequiredService<PromptLoader>();
    await promptLoader.LoadAllAsync();
}

// Seed policy rules on startup (idempotent)
if (!useInMemory)
{
    await SeedPolicyRules(app);
}

if (app.Environment.IsDevelopment() || useInMemory)
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

app.Run();

static async Task SeedPolicyRules(WebApplication app)
{
    using var scope = app.Services.CreateScope();
    var repository = scope.ServiceProvider.GetRequiredService<ICosmosPolicyRepository>();
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    var environment = scope.ServiceProvider.GetRequiredService<IWebHostEnvironment>();

    try
    {
        var seedFilePath = Path.Combine(environment.ContentRootPath, "seed", "policy-rules.json");
        if (!File.Exists(seedFilePath))
        {
            logger.LogWarning("Policy seed file not found at {Path}", seedFilePath);
            return;
        }

        var json = await File.ReadAllTextAsync(seedFilePath);
        var rules = JsonConvert.DeserializeObject<LoanOrigination.Models.PolicyRule[]>(json);

        if (rules == null || rules.Length == 0)
        {
            logger.LogWarning("No policy rules found in seed file");
            return;
        }

        logger.LogInformation("Seeding {Count} policy rules", rules.Length);

        foreach (var rule in rules)
        {
            await repository.UpsertAsync(rule);
        }

        logger.LogInformation("Policy rules seeded successfully");
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Failed to seed policy rules");
        // Don't throw — allow service to start
    }
}
