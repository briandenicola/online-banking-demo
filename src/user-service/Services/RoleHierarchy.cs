using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace UserService.Services;

/// <summary>
/// Expands a flat <c>role</c> claim into the set of roles it effectively grants,
/// per <c>config/role-hierarchy.yaml</c> (epic #332 §5.8.2).
/// </summary>
/// <remarks>
/// There is exactly one implementation of expansion, and it runs once, at token
/// issuance. Consumers read the <c>effectiveRoles</c> claim; nothing downstream
/// re-derives it. A second expansion is a second place for the ladder to be
/// subtly wrong.
/// </remarks>
public interface IRoleHierarchy
{
    /// <summary>
    /// Returns the role plus the transitive closure of everything it implies,
    /// lower-cased and de-duplicated, in stable order. An unknown role expands
    /// to itself so that a role added to the store before it is added to the
    /// hierarchy degrades to "no extra authority" rather than to an exception.
    /// </summary>
    IReadOnlyList<string> Expand(string role);

    /// <summary>
    /// Banking seniority for a role: the highest seniority across its effective
    /// roles. Approval signature slots compare against this
    /// (<c>minSeniority</c>). <c>admin</c> is deliberately 0 — platform power is
    /// not banking seniority.
    /// </summary>
    int SeniorityOf(string role);

    /// <summary>All role names known to the hierarchy.</summary>
    IReadOnlyCollection<string> KnownRoles { get; }
}

public sealed class RoleHierarchy : IRoleHierarchy
{
    public const string DefaultConfigPath = "config/role-hierarchy.yaml";

    private readonly Dictionary<string, RoleDefinition> _roles;
    private readonly Dictionary<string, IReadOnlyList<string>> _expansionCache = new(StringComparer.OrdinalIgnoreCase);

    private RoleHierarchy(Dictionary<string, RoleDefinition> roles)
    {
        _roles = roles;
    }

    public IReadOnlyCollection<string> KnownRoles => _roles.Keys;

    /// <summary>
    /// The hierarchy as ratified in §5.8.2, used when no config file is present
    /// (unit tests, and the in-memory dev mode). Kept in sync with
    /// <c>config/role-hierarchy.yaml</c>; the file is authoritative.
    /// </summary>
    public static RoleHierarchy Default { get; } = new(new Dictionary<string, RoleDefinition>(StringComparer.OrdinalIgnoreCase)
    {
        [Constants.Roles.User] = new() { Seniority = 0, Implies = new List<string>() },
        [Constants.Roles.Banker] = new() { Seniority = 1, Implies = new List<string>() },
        [Constants.Roles.Supervisor] = new() { Seniority = 2, Implies = new List<string> { Constants.Roles.Banker } },
        // admin implies NOTHING. See config/role-hierarchy.yaml for why.
        [Constants.Roles.Admin] = new() { Seniority = 0, Implies = new List<string>() },
    });

    /// <summary>
    /// Loads the hierarchy from YAML, falling back to <see cref="Default"/> when
    /// the file is missing or unparseable. Falling back is safe because the
    /// default is the strictest reading of the ruling: a corrupt file can only
    /// ever cost authority, never grant it.
    /// </summary>
    public static IRoleHierarchy Load(string? path, ILogger? logger = null)
    {
        logger ??= NullLogger.Instance;
        var resolved = string.IsNullOrWhiteSpace(path) ? DefaultConfigPath : path;

        if (!Path.IsPathRooted(resolved))
        {
            resolved = Path.Combine(AppContext.BaseDirectory, resolved);
        }

        if (!File.Exists(resolved))
        {
            logger.LogWarning(
                "Role hierarchy file not found at {Path} — falling back to the built-in hierarchy (§5.8.2)",
                resolved);
            return Default;
        }

        try
        {
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(CamelCaseNamingConvention.Instance)
                .IgnoreUnmatchedProperties()
                .Build();

            var document = deserializer.Deserialize<RoleHierarchyDocument>(File.ReadAllText(resolved));

            if (document?.Roles is null || document.Roles.Count == 0)
            {
                logger.LogWarning("Role hierarchy file {Path} declares no roles — falling back to the built-in hierarchy", resolved);
                return Default;
            }

            var roles = new Dictionary<string, RoleDefinition>(document.Roles, StringComparer.OrdinalIgnoreCase);
            var hierarchy = new RoleHierarchy(roles);

            // Fail fast on a cycle rather than looping at token issuance.
            foreach (var role in roles.Keys)
            {
                hierarchy.Expand(role);
            }

            logger.LogInformation(
                "Loaded role hierarchy v{Version} from {Path}: {Roles}",
                document.Version, resolved, string.Join(", ", roles.Keys));

            return hierarchy;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to load role hierarchy from {Path} — falling back to the built-in hierarchy", resolved);
            return Default;
        }
    }

    public IReadOnlyList<string> Expand(string role)
    {
        if (string.IsNullOrWhiteSpace(role))
        {
            return Array.Empty<string>();
        }

        if (_expansionCache.TryGetValue(role, out var cached))
        {
            return cached;
        }

        var ordered = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var visiting = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        Visit(role);

        var result = (IReadOnlyList<string>)ordered.AsReadOnly();
        _expansionCache[role] = result;
        return result;

        void Visit(string current)
        {
            var normalized = current.Trim().ToLowerInvariant();
            if (!seen.Add(normalized))
            {
                return;
            }

            if (!visiting.Add(normalized))
            {
                throw new InvalidOperationException($"Cycle detected in role hierarchy at '{normalized}'");
            }

            ordered.Add(normalized);

            if (_roles.TryGetValue(normalized, out var definition) && definition.Implies is { Count: > 0 })
            {
                foreach (var implied in definition.Implies)
                {
                    Visit(implied);
                }
            }

            visiting.Remove(normalized);
        }
    }

    public int SeniorityOf(string role)
    {
        var max = 0;
        foreach (var effective in Expand(role))
        {
            if (_roles.TryGetValue(effective, out var definition) && definition.Seniority > max)
            {
                max = definition.Seniority;
            }
        }

        return max;
    }

    private sealed class RoleHierarchyDocument
    {
        public int Version { get; set; }
        public Dictionary<string, RoleDefinition>? Roles { get; set; }
    }

    public sealed class RoleDefinition
    {
        public string? Description { get; set; }
        public int Seniority { get; set; }
        public List<string> Implies { get; set; } = new();
    }
}
