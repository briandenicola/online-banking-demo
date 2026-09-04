using Banking.Auth;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using Azure.Identity;
using StackExchange.Redis;
using System.Text;
using Banking.Observability;
using TransferService.Repositories;
using TransferService.Services;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("transfer-service");

// OpenTelemetry tracing
builder.Services.AddBankingOpenTelemetry("transfer-service");

// Add services to the container
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "Transfer Service", Version = "v1" });
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

// JWT authentication — issue #334.
// Audience, issuer, algorithm and key resolution all come from `config/jwt-audiences.yaml`
// via the shared registry. This service states only its own name; every other service used to
// restate the same validation policy independently, which is how nine files could agree on a
// single platform-wide audience with nothing in place to notice when they stopped agreeing.
builder.AddBankingJwtAuth("transfer-service");

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

if (useInMemory)
{
    builder.Services.AddLogging();
    // HTTP Client for service-to-service calls (account + transaction lookups)
    builder.Services.AddHttpClient();
    builder.Services.AddHttpContextAccessor();
    builder.Services.AddSingleton<ITransferService, InMemoryTransferService>();
}
else
{
    // Cosmos DB
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
        
        if (!string.IsNullOrEmpty(endpoint))
        {
            return new CosmosClient(endpoint, new DefaultAzureCredential(), clientOptions);
        }
        return new CosmosClient(configuration["CosmosDb:ConnectionString"], clientOptions);
    });

    // Repositories
    builder.Services.AddScoped<ITransferRepository, CosmosTransferRepository>();
    builder.Services.AddSingleton<IEventPublisher, RedisEventPublisher>();

    // HTTP Client for service-to-service calls
    builder.Services.AddHttpClient();
    builder.Services.AddHttpContextAccessor();

    // Decomposed transfer pipeline (validator → executor → event publisher)
    builder.Services.AddScoped<ITransferValidator, TransferValidator>();
    builder.Services.AddScoped<ITransferExecutor, TransferExecutor>();
    builder.Services.AddScoped<ITransferEventPublisher, TransferEventPublisher>();

    // Services
    builder.Services.AddScoped<ITransferService, TransferService.Services.TransferService>();
}

var app = builder.Build();

// Configure the HTTP request pipeline
if (app.Environment.IsDevelopment() || useInMemory)
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();

app.UseCorrelationId();

app.UseGlobalExceptionHandler();

app.UseCors();
app.UseAuthorization();

app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new { status = "healthy", service = "transfer-service", timestamp = DateTime.UtcNow }));
app.MapGet("/readyz", () => Results.Ok(new { status = "ready" }));

app.Run();