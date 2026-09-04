using System;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi;
using Swashbuckle.AspNetCore;
using System.Text;
using Azure.Identity;
using Banking.Observability;
using StackExchange.Redis;
using UserService.Repositories;
using UserService.Services;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
builder.Host.UseBankingSerilog("user-service");

// OpenTelemetry tracing
builder.Services.AddBankingOpenTelemetry("user-service");

// Add services to the container
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo { Title = "User Service", Version = "v1" });
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
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = builder.Configuration["Jwt:Issuer"],
        ValidAudience = builder.Configuration["Jwt:Audience"],
        IssuerSigningKey = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(builder.Configuration["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key is not configured")))
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
    var accountServiceUrl = builder.Configuration["ACCOUNT_SERVICE_URL"] ?? "http://account-service:8080";
    client.BaseAddress = new Uri(accountServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(10);
});

// Use in-memory database for development if configured
var useInMemory = builder.Configuration.GetValue<bool>("UseInMemoryDatabase", false);

// Shared infrastructure for thin controllers
builder.Services.AddHttpContextAccessor();
builder.Services.AddSingleton<IUserAgentParser, UserAgentParser>();
builder.Services.AddScoped<ILoginAuditService, LoginAuditService>();
builder.Services.AddScoped<IAccountProvisioningService, AccountProvisioningService>();

// Role hierarchy (epic #332 §5.8.2). Loaded once from config/role-hierarchy.yaml
// and used only at token issuance to expand the flat `role` claim into
// `effectiveRoles`. The hierarchy is a policy statement, not a constant, which is
// why it is a file and not a switch statement.
builder.Services.AddSingleton<IRoleHierarchy>(sp => RoleHierarchy.Load(
    builder.Configuration["RoleHierarchy:ConfigPath"],
    sp.GetService<ILogger<RoleHierarchy>>()));

if (useInMemory)
{
    builder.Services.AddLogging();
    builder.Services.AddSingleton<IUserService, InMemoryUserService>();
    builder.Services.AddSingleton<IAuthService, AuthService>();
}else
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

    // Repositories
    builder.Services.AddScoped<IUserRepository, CosmosUserRepository>();
    builder.Services.AddScoped<ILoginAuditRepository, CosmosLoginAuditRepository>();
    builder.Services.AddSingleton<IEventPublisher, RedisEventPublisher>();

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

app.UseGlobalExceptionHandler();

app.UseCors();
app.UseAuthorization();

app.MapControllers();

app.MapGet("/healthz", () => Results.Ok(new { status = "healthy", service = "user-service", timestamp = DateTime.UtcNow }));
app.MapGet("/readyz", () => Results.Ok(new { status = "ready" }));

// Promote the bootstrap admin if configured (Admin__BootstrapEmail env var)
var bootstrapEmail = builder.Configuration["Admin:BootstrapEmail"];

if (!useInMemory)
{
    using var scope = app.Services.CreateScope();
    var cosmosClient = scope.ServiceProvider.GetRequiredService<CosmosClient>();
    var config = scope.ServiceProvider.GetRequiredService<IConfiguration>();
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    var container = cosmosClient.GetContainer(config["CosmosDb:DatabaseName"], config["CosmosDb:ContainerName"]);

    try
    {
        // Check if any admin users exist
        var adminQuery = new QueryDefinition(
            "SELECT VALUE COUNT(1) FROM c WHERE c.Role = 'admin' OR c.role = 'admin'");
        var adminIterator = container.GetItemQueryIterator<int>(adminQuery);
        var adminResult = await adminIterator.ReadNextAsync();
        var adminCount = adminResult.FirstOrDefault();

        if (adminCount == 0)
        {
            if (!string.IsNullOrWhiteSpace(bootstrapEmail))
            {
                // Promote the user matching the bootstrap email
                var emailQuery = new QueryDefinition(
                        "SELECT * FROM c WHERE LOWER(c.Email) = @email OR LOWER(c.email) = @email")
                    .WithParameter("@email", bootstrapEmail.ToLowerInvariant());
                var emailIterator = container.GetItemQueryIterator<UserService.Models.User>(emailQuery);
                UserService.Models.User? bootstrapUser = null;
                while (emailIterator.HasMoreResults)
                {
                    var emailResult = await emailIterator.ReadNextAsync();
                    bootstrapUser = emailResult.FirstOrDefault();
                    if (bootstrapUser != null) break;
                }

                if (bootstrapUser != null)
                {
                    bootstrapUser.Role = global::UserService.Constants.Roles.Admin;
                    await container.ReplaceItemAsync(bootstrapUser, bootstrapUser.Id, new PartitionKey(bootstrapUser.Id));
                    logger.LogInformation("Promoted user {Username} ({Email}) to admin role via Admin__BootstrapEmail", bootstrapUser.Username, bootstrapUser.Email);
                }
                else
                {
                    logger.LogWarning("Admin__BootstrapEmail is set to '{Email}' but no matching user was found", bootstrapEmail);
                }
            }
            else
            {
                // Fall back to first-user convention
                var firstUserQuery = new QueryDefinition(
                    "SELECT * FROM c ORDER BY c.CreatedAt ASC, c.createdAt ASC OFFSET 0 LIMIT 1");
                var firstUserIterator = container.GetItemQueryIterator<UserService.Models.User>(firstUserQuery);
                var firstUserResult = await firstUserIterator.ReadNextAsync();
                var firstUser = firstUserResult.FirstOrDefault();

                if (firstUser != null)
                {
                    firstUser.Role = global::UserService.Constants.Roles.Admin;
                    await container.ReplaceItemAsync(firstUser, firstUser.Id, new PartitionKey(firstUser.Id));
                    logger.LogInformation("Promoted user {Username} ({Email}) to admin role — first user convention", firstUser.Username, firstUser.Email);
                }
            }
        }
    }
    catch (Exception ex)
    {
        logger.LogWarning(ex, "Failed to check/promote admin user on startup — non-critical");
    }

    // Bootstrap the banking authority ladder (epic #332 §5.8.3).
    //
    // The chicken-and-egg: promotion to `supervisor` is itself an L3 action, so
    // the Copilot harness may not create supervisors. Something outside the
    // harness must, and this is it — a Terraform-supplied identity, promoted at
    // startup, idempotently.
    //
    // Rejected alternatives, recorded so they are not re-proposed: a
    // harness-driven bootstrap (violates L3 outright), a manual Cosmos document
    // edit (unauditable, and exactly the "someone edits the database" path this
    // epic exists to eliminate), and an env-var superuser (a permanent standing
    // credential with no audit trail). Accordingly this promotes an EXISTING
    // registered identity; it never invents credentials.
    var bootstrapRoles = new[]
    {
        (Role: global::UserService.Constants.Roles.Supervisor,
         Email: builder.Configuration["Authority:BootstrapSupervisorEmail"]),
        (Role: global::UserService.Constants.Roles.Banker,
         Email: builder.Configuration["Authority:BootstrapBankerEmail"]),
    };

    foreach (var (role, email) in bootstrapRoles)
    {
        if (string.IsNullOrWhiteSpace(email))
        {
            continue;
        }

        try
        {
            // Idempotent: no-op on every boot once anybody holds the role.
            var existingQuery = new QueryDefinition(
                    "SELECT VALUE COUNT(1) FROM c WHERE c.Role = @role OR c.role = @role")
                .WithParameter("@role", role);
            var existingIterator = container.GetItemQueryIterator<int>(existingQuery);
            var existingResult = await existingIterator.ReadNextAsync();

            if (existingResult.FirstOrDefault() > 0)
            {
                logger.LogInformation("Role {Role} already held by an identity — bootstrap seed skipped", role);
                continue;
            }

            var targetQuery = new QueryDefinition(
                    "SELECT * FROM c WHERE LOWER(c.Email) = @email OR LOWER(c.email) = @email")
                .WithParameter("@email", email.ToLowerInvariant());
            var targetIterator = container.GetItemQueryIterator<UserService.Models.User>(targetQuery);
            UserService.Models.User? target = null;
            while (targetIterator.HasMoreResults)
            {
                var targetResult = await targetIterator.ReadNextAsync();
                target = targetResult.FirstOrDefault();
                if (target != null) break;
            }

            if (target == null)
            {
                logger.LogWarning(
                    "Bootstrap {Role} is configured as '{Email}' but no matching identity exists yet — register that identity and restart. No {Role} exists, so the authority ladder cannot be exercised until then.",
                    role, email, role);
                continue;
            }

            var previousRole = target.Role;
            target.Role = role;
            await container.ReplaceItemAsync(target, target.Id, new PartitionKey(target.Id));

            logger.LogWarning(
                "ROLE GRANT (bootstrap): {Username} ({Email}) granted role {Role}, previously {PreviousRole}",
                target.Username, target.Email, role, previousRole);
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Failed to seed bootstrap {Role} — non-critical", role);
        }
    }
}

app.Run();