using System.Text.RegularExpressions;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Banking.Auth;

/// <summary>
/// Thrown when the token model cannot be established safely. Every throw site in this
/// assembly is a fail-closed startup abort: a service that cannot prove which audience it
/// owns, or which finds signing material it has no business holding, must not serve traffic.
/// </summary>
public sealed class JwtConfigurationException : Exception
{
    public JwtConfigurationException(string message) : base(message) { }
}

/// <summary>
/// The parsed form of <c>config/jwt-audiences.yaml</c>.
///
/// This type is the ONLY place the audience model is interpreted. Services ask it what their
/// audience is rather than each declaring one, because #334's root cause was one value stated
/// independently in nine places — nine internally-coherent statements that happened to agree,
/// with nothing that would notice if they stopped.
/// </summary>
public sealed class JwtAudienceRegistry
{
    private readonly IReadOnlyDictionary<string, string> _audiences;
    private readonly HashSet<string> _mediatorAcceptedBy;
    private readonly HashSet<string> _mediatorRejectedBy;
    private readonly HashSet<string> _mediatorClients;

    /// <summary>Issuer (<c>iss</c>) value every token in the platform must carry.</summary>
    public string Issuer { get; }

    /// <summary>The one service permitted to hold signing material.</summary>
    public string IssuerService { get; }

    /// <summary>Audience presented by <c>authority-service</c> when executing an approved action.</summary>
    public string MediatorAudience { get; }

    public string SessionTokenUse { get; }

    public string MediatorTokenUse { get; }

    /// <summary>Audience set carried by a token minted at human login.</summary>
    public IReadOnlyList<string> SessionAudiences { get; }

    /// <summary>Config keys retired with the symmetric-key model; their presence is fatal.</summary>
    public IReadOnlyList<string> RetiredConfigKeys { get; }

    public IReadOnlyDictionary<string, string> Audiences => _audiences;

    private JwtAudienceRegistry(RegistryDocument document, string sourcePath)
    {
        if (document.Issuer is null || string.IsNullOrWhiteSpace(document.Issuer.Name))
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: 'issuer.name' is required. Without a pinned issuer, audience " +
                "scoping is decoration — any party able to sign could mint for any audience.");
        }

        if (document.Audiences is null || document.Audiences.Count == 0)
        {
            throw new JwtConfigurationException($"{sourcePath}: 'audiences' is empty.");
        }

        if (document.Mediator is null || string.IsNullOrWhiteSpace(document.Mediator.Audience))
        {
            throw new JwtConfigurationException($"{sourcePath}: 'mediator.audience' is required.");
        }

        if (document.Session is null || document.Session.Audiences is null || document.Session.Audiences.Count == 0)
        {
            throw new JwtConfigurationException($"{sourcePath}: 'session.audiences' is empty.");
        }

        Issuer = document.Issuer.Name;
        IssuerService = string.IsNullOrWhiteSpace(document.Issuer.Service)
            ? document.Issuer.Name
            : document.Issuer.Service!;
        _audiences = document.Audiences;
        MediatorAudience = document.Mediator.Audience;
        SessionAudiences = document.Session.Audiences;
        SessionTokenUse = string.IsNullOrWhiteSpace(document.Session.TokenUse) ? "session" : document.Session.TokenUse!;
        MediatorTokenUse = string.IsNullOrWhiteSpace(document.Mediator.TokenUse) ? "mediator" : document.Mediator.TokenUse!;
        RetiredConfigKeys = document.RetiredConfigKeys ?? new List<string>();

        _mediatorAcceptedBy = new HashSet<string>(document.Mediator.AcceptedBy ?? new List<string>(), StringComparer.Ordinal);
        _mediatorRejectedBy = new HashSet<string>(document.Mediator.RejectedBy ?? new List<string>(), StringComparer.Ordinal);
        _mediatorClients = new HashSet<string>(document.Mediator.Clients ?? new List<string>(), StringComparer.Ordinal);

        Validate(sourcePath);
    }

    private void Validate(string sourcePath)
    {
        // Audiences must be distinct, or two services silently share one and the whole point
        // of #334 is undone without any single file looking wrong.
        var duplicates = _audiences
            .GroupBy(pair => pair.Value, StringComparer.Ordinal)
            .Where(group => group.Count() > 1)
            .Select(group => $"{group.Key} <- {string.Join(", ", group.Select(p => p.Key))}")
            .ToList();

        if (duplicates.Count > 0)
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: audiences must be unique per service; found shared values: " +
                string.Join("; ", duplicates) +
                ". Two services sharing an audience reintroduces the platform-wide bearer token.");
        }

        var known = new HashSet<string>(_audiences.Values, StringComparer.Ordinal);

        // THE invariant of this file. A session token is what a human — and therefore what an
        // agent forwarding a human's token — can hold. If the mediator audience were in that
        // set, `authority-service` would stop being the sole executor of agent-originated
        // writes and the approval ladder would become decorative.
        if (SessionAudiences.Contains(MediatorAudience, StringComparer.Ordinal))
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: the mediator audience '{MediatorAudience}' appears in " +
                "'session.audiences'. A token any human or agent can obtain would then be " +
                "accepted as a broker token, defeating epic #332 §4.4 layer 2 entirely.");
        }

        foreach (var audience in SessionAudiences)
        {
            if (!known.Contains(audience))
            {
                throw new JwtConfigurationException(
                    $"{sourcePath}: session audience '{audience}' is not any service's audience.");
            }
        }

        if (known.Contains(MediatorAudience))
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: the mediator audience '{MediatorAudience}' is also a service " +
                "audience. It must name a capability, not a listener.");
        }

        foreach (var service in _mediatorAcceptedBy.Concat(_mediatorRejectedBy).Concat(_mediatorClients))
        {
            if (!_audiences.ContainsKey(service))
            {
                throw new JwtConfigurationException(
                    $"{sourcePath}: '{service}' is referenced under 'mediator' but has no audience entry.");
            }
        }

        var contradictions = _mediatorAcceptedBy.Intersect(_mediatorRejectedBy, StringComparer.Ordinal).ToList();
        if (contradictions.Count > 0)
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: {string.Join(", ", contradictions)} appear in BOTH " +
                "'mediator.acceptedBy' and 'mediator.rejectedBy'.");
        }

        if (!_mediatorRejectedBy.Contains("authority-service"))
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: 'authority-service' must appear in 'mediator.rejectedBy'. A " +
                "mediator token replayed at the mediator would let a downstream call be " +
                "laundered back through the approval broker.");
        }

        if (_mediatorClients.Contains("banker-copilot-service"))
        {
            throw new JwtConfigurationException(
                $"{sourcePath}: 'banker-copilot-service' must never be a mediator client. The " +
                "harness registers zero write tools by design; granting it the broker " +
                "credential would hand it back the affordance the design removes.");
        }
    }

    /// <summary>The audience the named service listens on. Unknown services are fatal.</summary>
    public string AudienceFor(string service)
    {
        if (_audiences.TryGetValue(service, out var audience))
        {
            return audience;
        }

        throw new JwtConfigurationException(
            $"Service '{service}' has no entry in the JWT audience registry. Add it to " +
            "config/jwt-audiences.yaml rather than inventing an audience locally — a locally " +
            "invented audience is exactly the drift #334 was filed for.");
    }

    /// <summary>
    /// The complete set of audiences the named service accepts: its own, plus the mediator
    /// audience when — and only when — the registry says it is executed against by the broker.
    /// </summary>
    public IReadOnlyList<string> ValidAudiencesFor(string service)
    {
        var audiences = new List<string> { AudienceFor(service) };

        if (_mediatorAcceptedBy.Contains(service))
        {
            audiences.Add(MediatorAudience);
        }

        return audiences;
    }

    public bool RejectsMediatorAudience(string service) => _mediatorRejectedBy.Contains(service);

    public bool IsMediatorClient(string service) => _mediatorClients.Contains(service);

    public bool IsIssuer(string service) => string.Equals(service, IssuerService, StringComparison.Ordinal);

    /// <summary>
    /// Narrowing is monotonic: the requested set must be a subset of what the presented token
    /// already carries. A count check would pass silently on a swapped element, so this is a
    /// set-membership test that names the offending audience when it fails.
    /// </summary>
    public static IReadOnlyList<string> Narrow(IEnumerable<string> held, IEnumerable<string> requested)
    {
        var heldSet = new HashSet<string>(held, StringComparer.Ordinal);
        var result = new List<string>();

        foreach (var audience in requested)
        {
            if (!heldSet.Contains(audience))
            {
                throw new JwtConfigurationException(
                    $"Cannot scope a token to '{audience}': the presented token does not carry " +
                    "it. Token exchange narrows only; it never widens.");
            }

            if (!result.Contains(audience, StringComparer.Ordinal))
            {
                result.Add(audience);
            }
        }

        if (result.Count == 0)
        {
            throw new JwtConfigurationException("A scoped token must carry at least one audience.");
        }

        return result;
    }

    /// <summary>Resource name of the copy compiled into this assembly.</summary>
    public const string EmbeddedResourceName = "Banking.Auth.jwt-audiences.yaml";

    public static JwtAudienceRegistry Load(string? configuredPath)
    {
        // An explicitly configured path wins, so an operator can override without a rebuild.
        // Note it is an error for that file to be missing: falling back to the embedded copy
        // after being pointed somewhere else would silently ignore the operator's intent.
        if (!string.IsNullOrWhiteSpace(configuredPath))
        {
            return Parse(ReadFile(configuredPath!), configuredPath!);
        }

        // Then a file discovered by walking up from the working directory — how `dotnet run`
        // and `dotnet test` see the repo's own config/ directory.
        var discovered = TryDiscover();
        if (discovered is not null)
        {
            return Parse(ReadFile(discovered), discovered);
        }

        // Finally the copy compiled in from the same source file. This is what containers use:
        // it means no service needs a config mount to know the audience model, and there is no
        // opportunity for a stale mounted copy to disagree with the code that reads it.
        using var stream = typeof(JwtAudienceRegistry).Assembly.GetManifestResourceStream(EmbeddedResourceName)
            ?? throw new JwtConfigurationException(
                "The JWT audience registry was not found on disk and is missing from the " +
                "Banking.Auth assembly. There is no fallback audience by design.");

        using var reader = new StreamReader(stream);
        return Parse(reader.ReadToEnd(), $"embedded:{EmbeddedResourceName}");
    }

    private static string ReadFile(string path)
    {
        try
        {
            return File.ReadAllText(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new JwtConfigurationException(
                $"Could not read the JWT audience registry at '{path}': {exception.Message}. " +
                "A service that cannot read the audience model has no safe default — there is " +
                "no fallback audience by design.");
        }
    }

    public static JwtAudienceRegistry Parse(string yaml, string sourcePath = "<inline>")
    {
        var deserializer = new DeserializerBuilder()
            .WithNamingConvention(CamelCaseNamingConvention.Instance)
            .IgnoreUnmatchedProperties()
            .Build();

        RegistryDocument? document;
        try
        {
            document = deserializer.Deserialize<RegistryDocument>(yaml);
        }
        catch (Exception exception)
        {
            throw new JwtConfigurationException($"{sourcePath} is not valid YAML: {exception.Message}");
        }

        if (document is null)
        {
            throw new JwtConfigurationException($"{sourcePath} is empty.");
        }

        return new JwtAudienceRegistry(document, sourcePath);
    }

    private static string? TryDiscover()
    {
        var candidates = new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() };

        foreach (var start in candidates)
        {
            var directory = new DirectoryInfo(start);
            while (directory is not null)
            {
                var candidate = Path.Combine(directory.FullName, "config", "jwt-audiences.yaml");
                if (File.Exists(candidate))
                {
                    return candidate;
                }

                directory = directory.Parent;
            }
        }

        return null;
    }

    private sealed class RegistryDocument
    {
        public IssuerDocument? Issuer { get; set; }
        public Dictionary<string, string>? Audiences { get; set; }
        public SessionDocument? Session { get; set; }
        public MediatorDocument? Mediator { get; set; }
        public List<string>? RetiredConfigKeys { get; set; }
    }

    private sealed class IssuerDocument
    {
        public string? Name { get; set; }
        public string? Service { get; set; }
    }

    private sealed class SessionDocument
    {
        public List<string>? Audiences { get; set; }
        public string? TokenUse { get; set; }
    }

    private sealed class MediatorDocument
    {
        public string? Audience { get; set; }
        public string? TokenUse { get; set; }
        public List<string>? Clients { get; set; }
        public List<string>? AcceptedBy { get; set; }
        public List<string>? RejectedBy { get; set; }
    }
}
