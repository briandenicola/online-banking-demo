using System;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Swashbuckle.AspNetCore;
using System.Text;
using Azure.Identity;
using Banking.Observability;
using StackExchange.Redis;
using UserService.Services;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("user-service");

// OpenTelemetry tracing
builder.Services.AddBankingOpenTelemetry("user-service");

// Add services to the container
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// JWT Authentication (always configured)
builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(options =>
{
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = true,
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

// HttpClient for account-service communication
builder.Services.AddHttpClient("AccountService", client =>
{
    var accountServiceUrl = builder.Configuration["Services:AccountServiceUrl"] ?? "http://account-service:8080";
    client.BaseAddress = new Uri(accountServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(10);
});

// Use in-memory database for development if configured
var useInMemory = builder.Configuration.GetValue<bool>("UseInMemoryDatabase", false);

if (useInMemory)
{
    builder.Services.AddLogging();
    builder.Services.AddSingleton<IUserService, InMemoryUserService>();
    builder.Services.AddSingleton<IAuthService, AuthService>();
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

    // Redis for event streaming (Entra ID auth when running in Azure)
    var redisConnStr = builder.Configuration["Redis:ConnectionString"] ?? "redis:6379";
    builder.Services.AddSingleton<IConnectionMultiplexer>(sp =>
    {
        var configOptions = ConfigurationOptions.Parse(redisConnStr);
        if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AZURE_CLIENT_ID")))
        {
            var credential = new DefaultAzureCredential();
            configOptions.ConfigureForAzureWithTokenCredentialAsync(credential).GetAwaiter().GetResult();
        }
        return ConnectionMultiplexer.Connect(configOptions);
    });

    // Services
    builder.Services.AddScoped<IUserService, UserService.Services.UserService>();
    builder.Services.AddScoped<IAuthService, AuthService>();
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

app.UseCors();

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new { status = "healthy", service = "user-service", timestamp = DateTime.UtcNow }));
app.MapGet("/readyz", () => Results.Ok(new { status = "ready" }));

app.Run();