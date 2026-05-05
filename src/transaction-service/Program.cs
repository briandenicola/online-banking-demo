using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Azure.Cosmos;
using Azure.Messaging.EventHubs.Producer;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using Swashbuckle.AspNetCore;
using System.Text;
using System.Text.Json;
using TransactionService.Services;

var builder = WebApplication.CreateBuilder(args);

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

// Configure Event Hub Producer
builder.Services.AddSingleton<EventHubProducerClient>(sp =>
{
    var connectionString = sp.GetRequiredService<IConfiguration>()["EventHub:ConnectionString"];
    var eventHubName = sp.GetRequiredService<IConfiguration>()["EventHub:Name"] ?? "banking-events";
    return new EventHubProducerClient(connectionString, eventHubName);
});

// Use in-memory database for development if configured
var useInMemory = builder.Configuration.GetValue<bool>("UseInMemoryDatabase", false);

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
        var cosmosClient = new CosmosClient(configuration["CosmosDb:ConnectionString"]);
        return cosmosClient;
    });

    // Services
    builder.Services.AddScoped<ITransactionService, TransactionService.Services.TransactionService>();
}

var app = builder.Build();

// Validate Azure connectivity on startup
using (var scope = app.Services.CreateScope())
{
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    
    logger.LogInformation("=" + new string('=', 49));
    logger.LogInformation("Validating Azure connectivity...");
    
    // Validate Cosmos DB connectivity
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
            logger.LogError("Ensure CosmosDb:ConnectionString, CosmosDb:DatabaseName, and CosmosDb:ContainerName are set");
        }
    }
    else
    {
        logger.LogInformation("ℹ️ Using in-memory database (skip Cosmos DB validation)");
    }
    
    // Validate Event Hub connectivity
    try
    {
        var eventHubProducer = scope.ServiceProvider.GetRequiredService<EventHubProducerClient>();
        var eventHubName = builder.Configuration["EventHub:Name"] ?? "banking-events";
        
        // Send a connectivity test event
        var testEvent = new Azure.Messaging.EventHubs.EventData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new { 
            type = "connectivity-test",
            timestamp = DateTime.UtcNow 
        })));
        
        await eventHubProducer.SendAsync(new[] { testEvent });
        logger.LogInformation($"✅ Event Hub connectivity verified for '{eventHubName}'");
    }
    catch (Exception ex)
    {
        logger.LogError($"❌ Event Hub connection FAILED: {ex.Message}");
        logger.LogError("Ensure EventHub:ConnectionString and EventHub:Name are set and Managed Identity has Azure Event Hubs Data Sender role");
    }
}

// Configure the HTTP request pipeline
if (app.Environment.IsDevelopment() || useInMemory)
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.Run();