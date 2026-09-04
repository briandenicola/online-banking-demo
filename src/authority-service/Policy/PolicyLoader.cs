using System.Globalization;
using AuthorityService.Models;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace AuthorityService.Policy;

/// <summary>
/// Loads, resolves and validates the declarative policy file.
///
/// <b>Fail closed.</b> If the file is missing, unparseable, or fails any validation rule, the
/// loader throws and the service does not start. There is no built-in default policy and no
/// code-level fallback for a missing threshold — a service that cannot read its policy has no
/// business deciding who may sign what.
/// </summary>
public class PolicyLoader
{
    private static readonly string[] ValidKinds = ["money", "count", "ratio", "duration_seconds"];

    /// <summary>Predicate operators that compare magnitudes. These REQUIRE a threshold reference.</summary>
    private static readonly string[] NumericOps = ["gte", "gt", "lte", "lt", "countGte"];

    /// <summary>Operators that take a literal value or value list.</summary>
    private static readonly string[] LiteralOps = ["eq", "ne", "in", "notIn", "intersects"];

    /// <summary>Operators that take no operand at all.</summary>
    private static readonly string[] NullaryOps = ["isTrue", "isFalse", "exists", "notEmpty", "empty"];

    private readonly IReadOnlyDictionary<string, string?> _environment;
    private readonly RoleHierarchy _roles;

    /// <summary>
    /// Convenience overload that discovers the ratified role hierarchy. Still fail-closed —
    /// <see cref="RoleHierarchy.Discover"/> throws rather than defaulting to an empty ladder.
    /// </summary>
    public PolicyLoader(IReadOnlyDictionary<string, string?> environment)
        : this(environment, RoleHierarchy.Discover())
    {
    }

    public PolicyLoader(IReadOnlyDictionary<string, string?> environment, RoleHierarchy roles)
    {
        _environment = environment;
        _roles = roles;
    }

    public static PolicyLoader FromConfiguration(IConfiguration configuration)
    {
        // Every POLICY_* key visible to the process is a candidate override. Reading through
        // IConfiguration rather than Environment directly keeps appsettings, env vars and
        // ConfigMap-mounted files on one resolution path.
        var map = configuration.AsEnumerable()
            .Where(kv => !string.IsNullOrEmpty(kv.Key))
            .GroupBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First().Value, StringComparer.OrdinalIgnoreCase);

        var configured = RoleHierarchyPath(configuration);

        return new PolicyLoader(map, string.IsNullOrWhiteSpace(configured)
            ? RoleHierarchy.Discover()
            : RoleHierarchy.LoadFromFile(configured));
    }

    /// <summary>
    /// Where the ratified role hierarchy lives. It is user-service's file; this service consumes
    /// it and never restates it. Absent configuration is fatal, not defaulted to "no ladder".
    /// </summary>
    public static string? RoleHierarchyPath(IConfiguration configuration) =>
        configuration["ROLE_HIERARCHY_PATH"];

    public ResolvedPolicy LoadFromFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new PolicyValidationException(
                "POLICY_FILE_PATH is not configured. The authority service refuses to start " +
                "without an explicit policy file — there is no default ladder.");
        }

        if (!File.Exists(path))
        {
            throw new PolicyValidationException(
                $"Policy file '{path}' does not exist. Failing closed: with no policy there is no " +
                "authority model, and starting anyway would mean deciding approvals by accident.");
        }

        return LoadFromYaml(File.ReadAllText(path), path);
    }

    public ResolvedPolicy LoadFromYaml(string yaml, string origin = "<inline>")
    {
        PolicyDocument document;

        try
        {
            // Unmatched keys are FATAL, not ignored. An escalator whose key was misspelled —
            // `raise_to` for `raiseTo` — would otherwise load as a rule that silently does
            // nothing, presenting as a policy that is in force when it is not. (Livingston, F-1.)
            var deserializer = new DeserializerBuilder()
                .WithNamingConvention(CamelCaseNamingConvention.Instance)
                .Build();

            document = deserializer.Deserialize<PolicyDocument>(yaml)
                       ?? throw new PolicyValidationException($"Policy file '{origin}' is empty.");
        }
        catch (PolicyValidationException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new PolicyValidationException($"Policy file '{origin}' could not be parsed: {ex.Message}", ex);
        }

        var thresholds = ResolveThresholds(document);

        // Seniority is STAMPED from the role hierarchy before validation and before the version
        // hash, so the resolved policy carries one definition of who is worth what — and a change
        // to the hierarchy moves policyVersion, because it genuinely changes the ruleset.
        StampSeniority(document);
        Validate(document, thresholds, origin, yaml);

        return new ResolvedPolicy
        {
            Document = document,
            Thresholds = thresholds,
            PolicyVersion = ResolvedPolicy.ComputeVersion(document, thresholds),
            LoadedAt = DateTime.UtcNow
        };
    }

    // ---- threshold resolution ----------------------------------------------------------

    private Dictionary<string, ResolvedThreshold> ResolveThresholds(PolicyDocument document)
    {
        var resolved = new Dictionary<string, ResolvedThreshold>(StringComparer.Ordinal);

        foreach (var (name, definition) in document.Thresholds)
        {
            if (string.IsNullOrWhiteSpace(definition.Env))
            {
                throw new PolicyValidationException(
                    $"Threshold '{name}' declares no env override key. Every threshold must be " +
                    "overridable without a code change.");
            }

            var overridden = _environment.TryGetValue(definition.Env, out var envValue)
                             && !string.IsNullOrWhiteSpace(envValue);

            // Resolution order, highest first: environment variable → file default. No third source.
            var value = overridden ? envValue!.Trim() : definition.Default;

            resolved[name] = new ResolvedThreshold
            {
                Name = name,
                Kind = definition.Kind,
                Env = definition.Env,
                Value = value,
                Description = definition.Description,
                OverriddenByEnv = overridden,
                CurrencyScale = definition.CurrencyScale ?? document.Defaults.CurrencyScale
            };
        }

        return resolved;
    }

    // ---- validation --------------------------------------------------------------------

    private void Validate(
        PolicyDocument document,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        string origin,
        string yaml)
    {
        var errors = new List<string>();

        RejectDeclaredSeniority(yaml, errors);

        if (document.ApiVersion != "authority/v1")
        {
            errors.Add($"apiVersion must be 'authority/v1'; found '{document.ApiVersion}'.");
        }

        if (string.IsNullOrWhiteSpace(document.Metadata.PolicyId))
        {
            errors.Add("metadata.policyId is required.");
        }

        ValidateDefaults(document, thresholds, errors);
        ValidateThresholdValues(thresholds, errors);
        ValidateRungs(document, errors);
        if (document.Defaults.SupervisorSeniority is not null)
        {
            errors.Add("defaults.supervisorSeniority is retired and must be removed. The L2 " +
                       "co-signature bar is derived from rungs.L2.cosignerRoles through the " +
                       "ratified role hierarchy. Leaving it silently ignored would let an " +
                       "operator believe they had tuned dual control when they had not.");
        }

        ValidateSignerRoles(document, errors);
        ValidateCapabilityScopes(document, errors);
        ValidateEscalators(document, thresholds, errors);
        ValidateActions(document, thresholds, errors);

        if (errors.Count > 0)
        {
            throw new PolicyValidationException(
                $"Policy file '{origin}' is invalid and the service will not start:{Environment.NewLine}" +
                string.Join(Environment.NewLine, errors.Select(e => "  - " + e)));
        }
    }

    private static void ValidateDefaults(
        PolicyDocument document,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        var defaults = document.Defaults;

        if (defaults.UnknownAction != "deny")
        {
            errors.Add("defaults.unknownAction must be 'deny'. An unknown action can never be allowed.");
        }

        if (defaults.TtlExpiryOutcome != SharedIdentifiers.Status.Denied)
        {
            errors.Add("defaults.ttlExpiryOutcome must be 'denied' (invariant I-6). Expiry means denied, " +
                       "never auto-approved, and this value is not configurable to anything else.");
        }

        if (defaults.CurrencyScale is < 0 or > 8)
        {
            errors.Add("defaults.currencyScale must be between 0 and 8.");
        }

        RequireThresholdRef(defaults.ApprovalTtl, "defaults.approvalTtl", "duration_seconds", thresholds, errors);
        RequireThresholdRef(defaults.RetentionSeconds, "defaults.retentionSeconds", "duration_seconds", thresholds, errors);

        if (defaults.BatchApproval.Enabled)
        {
            RequireThresholdRef(defaults.BatchApproval.MaxItems, "defaults.batchApproval.maxItems", "count", thresholds, errors);

            if (defaults.BatchApproval.MaxRung != "L1")
            {
                errors.Add("defaults.batchApproval.maxRung must be 'L1' (invariant I-10). Batch signing " +
                           "is never available at L2.");
            }

            if (!defaults.BatchApproval.SameActionTypeOnly)
            {
                errors.Add("defaults.batchApproval.sameActionTypeOnly must be true. A batch that spans " +
                           "action types is 'Approve All' with extra steps.");
            }
        }

        foreach (var key in defaults.EvidenceRequired.Where(k => !document.Evidence.ContainsKey(k)))
        {
            errors.Add($"defaults.evidenceRequired references undefined evidence key '{key}'.");
        }
    }

    private static void ValidateThresholdValues(
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        var seenEnv = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        foreach (var (name, threshold) in thresholds)
        {
            if (!ValidKinds.Contains(threshold.Kind))
            {
                errors.Add($"Threshold '{name}' has unknown kind '{threshold.Kind}'. " +
                           $"Valid kinds: {string.Join(", ", ValidKinds)}.");
                continue;
            }

            if (seenEnv.TryGetValue(threshold.Env, out var other))
            {
                errors.Add($"Thresholds '{name}' and '{other}' both claim env override " +
                           $"'{threshold.Env}'. One env var may drive exactly one threshold.");
            }
            else
            {
                seenEnv[threshold.Env] = name;
            }

            if (string.IsNullOrWhiteSpace(threshold.Value))
            {
                errors.Add($"Threshold '{name}' resolved to an empty value.");
                continue;
            }

            switch (threshold.Kind)
            {
                case "money":
                    if (!decimal.TryParse(threshold.Value, NumberStyles.Number, CultureInfo.InvariantCulture, out var money))
                    {
                        errors.Add($"Threshold '{name}' (money) value '{threshold.Value}' is not a decimal.");
                    }
                    else if (Math.Round(money, threshold.CurrencyScale, MidpointRounding.ToEven) != money)
                    {
                        errors.Add($"Threshold '{name}' (money) value '{threshold.Value}' carries more " +
                                   $"precision than its currency scale of {threshold.CurrencyScale}.");
                    }
                    break;

                case "ratio":
                    if (!decimal.TryParse(threshold.Value, NumberStyles.Number, CultureInfo.InvariantCulture, out _))
                    {
                        errors.Add($"Threshold '{name}' (ratio) value '{threshold.Value}' is not a decimal.");
                    }
                    break;

                case "count":
                case "duration_seconds":
                    if (!long.TryParse(threshold.Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var whole))
                    {
                        errors.Add($"Threshold '{name}' ({threshold.Kind}) value '{threshold.Value}' is not an integer.");
                    }
                    else if (whole < 0)
                    {
                        errors.Add($"Threshold '{name}' ({threshold.Kind}) value '{threshold.Value}' is negative.");
                    }
                    break;
            }
        }
    }

    private static void ValidateRungs(PolicyDocument document, List<string> errors)
    {
        foreach (var rung in RungOrder.All)
        {
            var key = RungOrder.ToWire(rung);

            if (!document.Rungs.ContainsKey(key))
            {
                errors.Add($"rungs.{key} is not defined. The ladder has exactly three rungs and all must be declared.");
            }
        }

        // `distinctIdentities` is retired. Rejecting it is deliberate: silently ignoring the key
        // would let an operator write `distinctIdentities: 1`, read it back, and believe they had
        // relaxed dual control — when separation of duties now lives in the signature slots and
        // is not reachable from the policy file at all. A dead knob that looks live is worse than
        // no knob.
        foreach (var (key, definition) in document.Rungs)
        {
            if (definition.DistinctIdentities is not null)
            {
                errors.Add($"rungs.{key}.distinctIdentities is retired and must be removed. " +
                           "Separation of duties is enforced per signature slot via mustDifferFrom, " +
                           "which names the excluded identity instead of counting heads.");
            }
        }

        if (document.Rungs.TryGetValue("L1", out var l1) && l1.RequiredSigners < 1)
        {
            errors.Add("rungs.L1.requiredSigners must be at least 1. A human always signs (invariant I-1).");
        }

        if (document.Rungs.TryGetValue("L2", out var l2))
        {
            if (l2.RequiredSigners < 2)
            {
                errors.Add("rungs.L2.requiredSigners must be at least 2. Dual control is definitional.");
            }


            if (l2.CosignerRoles.Count == 0)
            {
                errors.Add("rungs.L2.cosignerRoles must list at least one role that may co-sign.");
            }
        }

        if (document.Rungs.TryGetValue("L3", out var l3) && l3.Proposable)
        {
            errors.Add("rungs.L3.proposable must be false. L3 means the agent may not even propose.");
        }
    }

    private void StampSeniority(PolicyDocument document)
    {
        foreach (var (name, role) in document.SignerRoles)
        {
            role.Seniority = _roles.Has(name) ? _roles.SeniorityOf(name) : -1;
        }
    }

    /// <summary>
    /// Rejects a policy that declares <c>seniority:</c> under a signer role. The field is
    /// <c>[YamlIgnore]</c>, so a declaration would otherwise be dropped in silence — the operator
    /// would read a number in the file, believe it was in force, and be wrong. Detected by
    /// re-reading the raw YAML rather than by the type system, precisely because the type system
    /// has been told to look away.
    /// </summary>
    private static void RejectDeclaredSeniority(string yaml, List<string> errors)
    {
        Dictionary<string, object>? raw;

        try
        {
            raw = new DeserializerBuilder()
                .WithNamingConvention(CamelCaseNamingConvention.Instance)
                .Build()
                .Deserialize<Dictionary<string, object>>(yaml);
        }
        catch
        {
            return; // Structural parse errors are reported by the typed load.
        }

        if (raw is null || !raw.TryGetValue("signerRoles", out var block)) return;
        if (block is not IDictionary<object, object> roles) return;

        foreach (var entry in roles)
        {
            if (entry.Value is not IDictionary<object, object> body) continue;

            if (body.Keys.Any(k => string.Equals(k?.ToString(), "seniority", StringComparison.OrdinalIgnoreCase)))
            {
                errors.Add($"signerRoles.{entry.Key}.seniority must not be declared. Banking " +
                           "seniority is taken from the ratified role-hierarchy.yaml; stating it " +
                           "here creates a second definition that silently outvotes the first.");
            }
        }
    }

    /// <summary>
    /// Cross-file agreement with the ratified role hierarchy, enforced at startup and fatal on
    /// mismatch.
    ///
    /// <para>
    /// This exists because two internally-coherent files disagreed and nothing compared them: the
    /// claim <c>user</c> — every retail customer — was mapped onto signer role <c>banker</c>, and
    /// <c>admin</c> was given a banking seniority above supervisor's. Neither file was wrong on
    /// its own. A warning would not do; this bug class is silent by construction, so it refuses
    /// to start.
    /// </para>
    /// </summary>
    private void ValidateSignerRoles(PolicyDocument document, List<string> errors)
    {
        if (document.SignerRoles.Count == 0)
        {
            errors.Add("signerRoles is empty; no principal could ever satisfy a signature slot.");
        }

        foreach (var (name, role) in document.SignerRoles)
        {
            if (!_roles.Has(name))
            {
                errors.Add($"signerRoles.{name} is not a role in the ratified role hierarchy " +
                           $"({_roles.Origin}). This service consumes that ladder; it may not invent a rung.");
                continue;
            }

            if (role.ClaimValues.Count == 0)
            {
                errors.Add($"signerRoles.{name}.claimValues is empty.");
            }

            foreach (var claim in role.ClaimValues)
            {
                if (!string.Equals(claim, name, StringComparison.OrdinalIgnoreCase))
                {
                    errors.Add($"signerRoles.{name}.claimValues contains '{claim}', which is not a " +
                               $"spelling of '{name}'. A claim may only denote its own role: mapping " +
                               "one role's claim onto another silently promotes everyone who holds it.");
                }
            }
        }

        foreach (var (key, rung) in document.Rungs)
        {
            foreach (var role in rung.SignerRoles.Concat(rung.CosignerRoles).Distinct(StringComparer.Ordinal))
            {
                if (!document.SignerRoles.ContainsKey(role))
                {
                    errors.Add($"rungs.{key} lists signer role '{role}', which is not defined in signerRoles.");
                    continue;
                }

                if (!_roles.Has(role) || _roles.SeniorityOf(role) < 1)
                {
                    errors.Add($"rungs.{key} lists '{role}', which carries no banking seniority in " +
                               $"{_roles.Origin}. Platform authority is not banking authority — a role " +
                               "that implies neither banker nor supervisor must never be able to fill a " +
                               "signature slot, or one identity could satisfy both sides of dual control.");
                }
            }

            if (rung.OutOfHarness && rung.SignerRoles.Count > 0)
            {
                errors.Add($"rungs.{key} is outOfHarness, so it must declare platformRoles and no " +
                           "signerRoles. An out-of-harness rung is handled in the break-glass console; " +
                           "it is not a rung this service collects signatures for.");
            }

            foreach (var role in rung.PlatformRoles)
            {
                if (!_roles.Has(role))
                {
                    errors.Add($"rungs.{key}.platformRoles references '{role}', which is not a role in " +
                               $"{_roles.Origin}.");
                }
            }

            if (!rung.OutOfHarness && rung.RequiredSigners > 1 && rung.CosignerRoles.Count == 0)
            {
                errors.Add($"rungs.{key} requires {rung.RequiredSigners} signers but names no " +
                           "cosignerRoles. The co-signer's seniority bar is DERIVED from that list; " +
                           "an empty list is a slot with no bar, not a slot with a default bar.");
            }

            if (rung.PlatformRoles.Count > 0 && !rung.OutOfHarness)
            {
                errors.Add($"rungs.{key} declares platformRoles but is not marked outOfHarness. " +
                           "Platform roles have no standing inside the ladder.");
            }
        }
    }

    /// <summary>
    /// Capability scopes gate what the harness may READ and WRITE on a principal's behalf. They
    /// drifted the same way the rungs did — `admin` was listed on every scope, making a role with
    /// no banking standing a superset for data access. Same rule, so: same check.
    /// </summary>
    private void ValidateCapabilityScopes(PolicyDocument document, List<string> errors)
    {
        foreach (var (scope, definition) in document.CapabilityScopes)
        {
            if (definition.Roles.Count == 0)
            {
                errors.Add($"capabilityScopes.{scope} names no roles.");
            }

            foreach (var role in definition.Roles)
            {
                if (!document.SignerRoles.ContainsKey(role))
                {
                    errors.Add($"capabilityScopes.{scope} references '{role}', which is not a signer role.");
                    continue;
                }

                if (!_roles.Has(role) || _roles.SeniorityOf(role) < 1)
                {
                    errors.Add($"capabilityScopes.{scope} grants '{role}', which carries no banking " +
                               $"seniority in {_roles.Origin}.");
                }
            }
        }
    }

    private static void ValidateEscalators(
        PolicyDocument document,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (var escalator in document.Escalators)
        {
            if (string.IsNullOrWhiteSpace(escalator.Id))
            {
                errors.Add("An escalator has no id.");
                continue;
            }

            if (!seen.Add(escalator.Id))
            {
                errors.Add($"Duplicate escalator id '{escalator.Id}'.");
            }

            ValidateRaise(escalator.Id, escalator.RaiseTo, escalator.RaiseBy, escalator.MinRung, errors);
            ValidatePredicate($"escalator '{escalator.Id}'", escalator.When, thresholds, errors);

            RequireOptionalThresholdRef(escalator.MinSigners, $"escalator '{escalator.Id}'.minSigners", "count", thresholds, errors);
            RequireOptionalThresholdRef(escalator.MinSeniority, $"escalator '{escalator.Id}'.minSeniority", "count", thresholds, errors);

            if (string.IsNullOrWhiteSpace(escalator.ReasonTemplate))
            {
                errors.Add($"escalator '{escalator.Id}' has no reasonTemplate. " +
                           "'It escalated' is not an explanation a signer can act on.");
            }
        }
    }

    private static void ValidateActions(
        PolicyDocument document,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        if (document.ActionTypes.Count == 0)
        {
            errors.Add("actionTypes is empty; the service would refuse every action.");
        }

        foreach (var (actionId, action) in document.ActionTypes)
        {
            ValidateActionId(actionId, errors);

            Rung baseRung;

            try
            {
                baseRung = RungOrder.Parse(action.BaseRung);
            }
            catch (PolicyValidationException ex)
            {
                errors.Add($"action '{actionId}': {ex.Message}");
                continue;
            }

            if (action.BaseSigners < 1)
            {
                errors.Add($"action '{actionId}'.baseSigners must be at least 1 (invariant I-1).");
            }

            if (string.IsNullOrWhiteSpace(action.DisplayName))
            {
                errors.Add($"action '{actionId}'.displayName is required; the UI renders it verbatim.");
            }

            var proposable = baseRung != Rung.L3 && action.AgentMayPropose;

            if (proposable)
            {
                if (action.Target is null || string.IsNullOrWhiteSpace(action.Target.Service)
                                          || string.IsNullOrWhiteSpace(action.Target.Path))
                {
                    errors.Add($"action '{actionId}' is proposable but declares no target service/path.");
                }

                if (action.HashFields.Count == 0)
                {
                    errors.Add($"action '{actionId}' declares no hashFields. A signature must bind to " +
                               "something specific, and an empty projection binds to nothing.");
                }
            }

            foreach (var moneyField in action.MoneyFields.Where(f => !action.HashFields.Contains(f)))
            {
                errors.Add($"action '{actionId}'.moneyFields entry '{moneyField}' is not in hashFields. " +
                           "A money field outside the signed projection is a figure nobody signed.");
            }

            foreach (var key in action.RequiredEvidence.Where(k => !document.Evidence.ContainsKey(k)))
            {
                errors.Add($"action '{actionId}' requires undefined evidence key '{key}'.");
            }

            RequireOptionalThresholdRef(action.ApprovalTtl, $"action '{actionId}'.approvalTtl", "duration_seconds", thresholds, errors);
            RequireOptionalThresholdRef(action.BatchMaxItems, $"action '{actionId}'.batchMaxItems", "count", thresholds, errors);

            foreach (var rule in action.Rules)
            {
                var label = $"action '{actionId}' rule '{rule.Id}'";

                if (string.IsNullOrWhiteSpace(rule.Id))
                {
                    errors.Add($"action '{actionId}' has a rule with no id.");
                }

                ValidateRaise(label, rule.RaiseTo, rule.RaiseBy, minRung: null, errors);
                ValidatePredicate(label, rule.When, thresholds, errors);
                RequireOptionalThresholdRef(rule.MinSigners, $"{label}.minSigners", "count", thresholds, errors);
                RequireOptionalThresholdRef(rule.MinSeniority, $"{label}.minSeniority", "count", thresholds, errors);

                if (string.IsNullOrWhiteSpace(rule.ReasonTemplate))
                {
                    errors.Add($"{label} has no reasonTemplate.");
                }
            }
        }
    }

    /// <summary>Action ids are policy lookup keys: <c>&lt;domain&gt;.&lt;entity&gt;.&lt;verb&gt;</c> or <c>&lt;domain&gt;.&lt;verb&gt;</c> (epic §0.1).</summary>
    private static void ValidateActionId(string actionId, List<string> errors)
    {
        var segments = actionId.Split('.');

        if (segments.Length is < 2 or > 3 || segments.Any(s => s.Length == 0))
        {
            errors.Add($"action id '{actionId}' does not follow '<domain>.<entity>.<verb>' or '<domain>.<verb>'.");
            return;
        }

        if (segments.Any(s => s.Any(c => !char.IsAsciiLetterLower(c) && c != '_')))
        {
            errors.Add($"action id '{actionId}' must be lowercase ASCII with underscores only.");
        }
    }

    private static void ValidateRaise(string label, string? raiseTo, int? raiseBy, string? minRung, List<string> errors)
    {
        if (raiseTo is null && raiseBy is null && minRung is null)
        {
            errors.Add($"{label} declares no raiseTo/raiseBy/minRung; it could never affect the outcome.");
        }

        if (raiseBy is < 0)
        {
            errors.Add($"{label} declares a negative raiseBy. Nothing may lower a rung (invariant I-4), " +
                       "and the grammar does not admit a lowering operator.");
        }

        foreach (var (value, field) in new[] { (raiseTo, "raiseTo"), (minRung, "minRung") })
        {
            if (value is null) continue;

            try
            {
                RungOrder.Parse(value);
            }
            catch (PolicyValidationException ex)
            {
                errors.Add($"{label}.{field}: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// The "no magic numbers" guard, enforced at load rather than by a grep in CI: a magnitude
    /// comparison MUST reference a named, env-overridable threshold, and may not carry a literal.
    /// </summary>
    private static void ValidatePredicate(
        string label,
        PredicateDefinition predicate,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(predicate.Field))
        {
            errors.Add($"{label} predicate has no field.");
        }

        if (NumericOps.Contains(predicate.Op))
        {
            if (string.IsNullOrWhiteSpace(predicate.Threshold))
            {
                errors.Add($"{label} predicate uses '{predicate.Op}' without a threshold reference. " +
                           "Magnitude comparisons must name a threshold; literal numbers are not " +
                           "expressible in a policy rule.");
            }
            else if (!thresholds.ContainsKey(predicate.Threshold))
            {
                errors.Add($"{label} predicate references undefined threshold '{predicate.Threshold}'.");
            }

            if (predicate.Value is not null || predicate.Values is not null)
            {
                errors.Add($"{label} predicate uses '{predicate.Op}' with a literal value. " +
                           "Use a threshold reference instead.");
            }
        }
        else if (LiteralOps.Contains(predicate.Op))
        {
            if (predicate.Value is null && (predicate.Values is null || predicate.Values.Count == 0))
            {
                errors.Add($"{label} predicate uses '{predicate.Op}' with no value or values.");
            }

            if (predicate.Threshold is not null)
            {
                errors.Add($"{label} predicate uses '{predicate.Op}' with a threshold reference; " +
                           "equality/membership operators take literals.");
            }

            foreach (var literal in Literals(predicate))
            {
                if (decimal.TryParse(literal, NumberStyles.Number, CultureInfo.InvariantCulture, out _))
                {
                    errors.Add($"{label} predicate compares against the numeric literal '{literal}'. " +
                               "Every number in this policy must be a named threshold with an env override.");
                }
            }
        }
        else if (!NullaryOps.Contains(predicate.Op))
        {
            errors.Add($"{label} predicate uses unknown operator '{predicate.Op}'. Valid operators: " +
                       $"{string.Join(", ", NumericOps.Concat(LiteralOps).Concat(NullaryOps))}.");
        }
    }

    private static IEnumerable<string> Literals(PredicateDefinition predicate)
    {
        if (predicate.Value is not null and not bool)
        {
            yield return Convert.ToString(predicate.Value, CultureInfo.InvariantCulture) ?? string.Empty;
        }

        foreach (var value in predicate.Values ?? [])
        {
            yield return value;
        }
    }

    private static void RequireThresholdRef(
        string? reference,
        string label,
        string expectedKind,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(reference))
        {
            errors.Add($"{label} is required and must name a threshold.");
            return;
        }

        RequireOptionalThresholdRef(reference, label, expectedKind, thresholds, errors);
    }

    private static void RequireOptionalThresholdRef(
        string? reference,
        string label,
        string expectedKind,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds,
        List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(reference)) return;

        if (!thresholds.TryGetValue(reference, out var threshold))
        {
            errors.Add($"{label} references undefined threshold '{reference}'.");
            return;
        }

        if (threshold.Kind != expectedKind)
        {
            errors.Add($"{label} references threshold '{reference}' of kind '{threshold.Kind}', " +
                       $"but a '{expectedKind}' threshold is required.");
        }
    }
}
