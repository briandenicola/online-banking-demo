using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using Azure.Identity;
using StackExchange.Redis;
using System.Text;
using Banking.Observability;
using TransactionService.Services;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("transaction-service");

// OpenTelemetry tracing
builder.Services.AddBankingOpenTelemetry("transaction-service");

// Add services to the container
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Transaction Service", Version = "v1" });
    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the Bearer scheme",
        Name = "Authorization",
        In = ParameterLocation.Header,
        Type = SecuritySchemeType.Http,
        Scheme = "bearer"
    });
    c.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme { Reference = new OpenApiReference { Id = "Bearer", Type = ReferenceType.SecurityScheme } },
            Array.Empty<string>()
        }
    });
});

// JWT Authentication (always configured)
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
        ValidateIssuer = false,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = builder.Configuration["Jwt:Issuer"],
        ValidAudience = builder.Configuration["Jwt:Audience"],
        IssuerSigningKey = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"]))
    };
});

builder.Services.AddAuthorization();

// CORS for local development
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

// Configure Redis (Entra ID auth when running in Azure)
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

// Use in-memory database for development if configured
var useInMemory = builder.Configuration.GetValue<bool>("UseInMemoryDatabase", false);

// HTTP Client for service-to-service calls (account balance updates)
builder.Services.AddHttpClient();
builder.Services.AddHttpContextAccessor();

if (useInMemory)
{
    builder.Services.AddLogging();
    builder.Services.AddSingleton<ITransactionService, InMemoryTransactionService>();
}
else
{
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

    // Services
    builder.Services.AddScoped<ITransactionService, TransactionService.Services.TransactionService>();
}

var app = builder.Build();

// Validate connectivity on startup
using (var scope = app.Services.CreateScope())
{
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    
    logger.LogInformation("=" + new string('=', 49));
    logger.LogInformation("Validating connectivity...");
    
    if (!useInMemory)
    {
        try
        {
            var cosmosClient = scope.ServiceProvider.GetService<CosmosClient>();
            if (cosmosClient != null)
            {
                var databaseName = builder.Configuration["CosmosDb:DatabaseName"];
                var containerName = builder.Configuration["CosmosDb:ContainerName"];
                var container = cosmosClient.GetContainer(databaseName, containerName);
                var query = container.GetItemQueryIterator<dynamic>("SELECT 1");
                await query.ReadNextAsync();
                logger.LogInformation("✅ Cosmos DB connectivity verified");
            }
        }
        catch (Exception ex)
        {
            logger.LogError($"❌ Cosmos DB connection FAILED: {ex.Message}");
        }
    }
    else
    {
        logger.LogInformation("ℹ️ Using in-memory database (skip Cosmos DB validation)");
    }
    
    // Validate Redis connectivity
    try
    {
        var redis = scope.ServiceProvider.GetRequiredService<IConnectionMultiplexer>();
        var db = redis.GetDatabase();
        await db.PingAsync();
        logger.LogInformation("✅ Redis connectivity verified");
    }
    catch (Exception ex)
    {
        logger.LogWarning($"⚠️ Redis connection not available: {ex.Message}");
    }
}

// Configure the HTTP request pipeline
if (app.Environment.IsDevelopment() || useInMemory)
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();

app.UseCorrelationId();

app.UseCors();

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new { status = "healthy", service = "transaction-service", timestamp = DateTime.UtcNow }));
app.MapGet("/readyz", () => Results.Ok(new { status = "ready" }));

app.Run();