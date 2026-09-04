using AuthorityService.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace AuthorityService.Policy;

/// <summary>
/// The banking role ladder, <b>consumed</b> from <c>user-service</c>'s ratified
/// <c>role-hierarchy.yaml</c> — never restated here.
///
/// <para>
/// This type exists because of a live privilege escalation. The authority policy file used to
/// declare its own claim-to-seniority map, which drifted from the token issuer's in two ways at
/// once: the claim <c>user</c> — held by every retail customer — was mapped to signer role
/// <c>banker</c> at seniority 1, and <c>admin</c> was given seniority 3, above supervisor, while
/// the ratified model puts it at 0 with no banking authority at all. Both files were internally
/// coherent. Neither service could see the defect alone.
/// </para>
///
/// <para>
/// So seniority now has exactly one definition. The policy file may name a signer role and the
/// claim spellings that denote it; it may not say what that role is worth. That is Danny's
/// duplication rule applied to the role model: anything restated in two artifacts must be derived
/// from one source or checked against one source, never maintained in parallel by careful people.
/// </para>
/// </summary>
public class RoleHierarchy
{
    public required IReadOnlyDictionary<string, RoleDefinition> Roles { get; init; }

    public required string Origin { get; init; }

    public bool Has(string role) => Roles.ContainsKey(role);

    public int SeniorityOf(string role) =>
        Roles.TryGetValue(role, out var definition)
            ? definition.Seniority
            : throw new PolicyValidationException(
                $"Role '{role}' is not defined in the ratified role hierarchy ({Origin}).");

    /// <summary>
    /// Locates the ratified hierarchy without being told where it is: the deployed path first,
    /// then the in-repo source of truth. Every candidate is an explicit location and a miss is an
    /// exception — there is no "no hierarchy found, carry on" branch, because that branch would
    /// mean starting with an empty ladder that no signature could ever be checked against.
    /// </summary>
    public static RoleHierarchy Discover()
    {
        var candidates = new List<string>
        {
            Environment.GetEnvironmentVariable("ROLE_HIERARCHY_PATH") ?? string.Empty,
            Path.Combine(AppContext.BaseDirectory, "config", "role-hierarchy.yaml"),
            Path.Combine(Directory.GetCurrentDirectory(), "config", "role-hierarchy.yaml")
        };

        var dir = new DirectoryInfo(AppContext.BaseDirectory);

        while (dir is not null)
        {
            candidates.Add(Path.Combine(dir.FullName, "src", "user-service", "config", "role-hierarchy.yaml"));
            dir = dir.Parent;
        }

        var found = candidates.FirstOrDefault(c => !string.IsNullOrWhiteSpace(c) && File.Exists(c));

        if (found is null)
        {
            throw new PolicyValidationException(
                "The ratified role hierarchy (role-hierarchy.yaml) could not be located. Set " +
                "ROLE_HIERARCHY_PATH. Failing closed: without it this service has no definition " +
                "of who outranks whom.");
        }

        return LoadFromFile(found);
    }

    public static RoleHierarchy LoadFromFile(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new PolicyValidationException(
                "ROLE_HIERARCHY_PATH is not configured. The authority service refuses to start " +
                "without the ratified role hierarchy: seniority is what decides who may sign, " +
                "and inventing it locally is how the ladder gets a rung the customer base can " +
                "stand on.");
        }

        if (!File.Exists(path))
        {
            throw new PolicyValidationException(
                $"Role hierarchy file '{path}' does not exist. Failing closed — see " +
                "user-service's config/role-hierarchy.yaml, which is the single source for " +
                "banking seniority.");
        }

        return LoadFromYaml(File.ReadAllText(path), path);
    }

    public static RoleHierarchy LoadFromYaml(string yaml, string origin = "<inline>")
    {
        RoleHierarchyDocument document;

        try
        {
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(CamelCaseNamingConvention.Instance)
                .Build();

            document = deserializer.Deserialize<RoleHierarchyDocument>(yaml)
                       ?? throw new PolicyValidationException($"Role hierarchy '{origin}' is empty.");
        }
        catch (PolicyValidationException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new PolicyValidationException(
                $"Role hierarchy '{origin}' could not be parsed: {ex.Message}", ex);
        }

        var errors = new List<string>();

        if (document.Roles.Count == 0)
        {
            errors.Add("roles is empty.");
        }

        foreach (var (name, role) in document.Roles)
        {
            if (role.Seniority < 0)
            {
                errors.Add($"roles.{name}.seniority is negative.");
            }

            foreach (var implied in role.Implies)
            {
                if (!document.Roles.ContainsKey(implied))
                {
                    errors.Add($"roles.{name}.implies references unknown role '{implied}'.");
                }
            }
        }

        if (errors.Count > 0)
        {
            throw new PolicyValidationException(
                $"Role hierarchy '{origin}' is invalid and the service will not start:" +
                Environment.NewLine + "- " + string.Join(Environment.NewLine + "- ", errors));
        }

        return new RoleHierarchy
        {
            Roles = document.Roles,
            Origin = origin
        };
    }

    /// <summary>
    /// Expands a principal's claimed roles through <c>implies</c>. Mirrors what the token issuer
    /// already did — this is a safety net for a token minted before a hierarchy change, not a
    /// second implementation of the ladder: both read the same file.
    /// </summary>
    public IReadOnlyCollection<string> Expand(IEnumerable<string> roles)
    {
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Queue<string>(roles);

        while (pending.Count > 0)
        {
            var role = pending.Dequeue();

            if (!result.Add(role)) continue;
            if (!Roles.TryGetValue(role, out var definition)) continue;

            foreach (var implied in definition.Implies) pending.Enqueue(implied);
        }

        return result;
    }
}

public class RoleHierarchyDocument
{
    public int Version { get; set; }

    public Dictionary<string, RoleDefinition> Roles { get; set; } = [];
}

public class RoleDefinition
{
    public string Description { get; set; } = string.Empty;

    public int Seniority { get; set; }

    public List<string> Implies { get; set; } = [];
}
