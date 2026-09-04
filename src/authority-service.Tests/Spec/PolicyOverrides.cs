namespace BankerCopilotTests.Spec;

/// <summary>
/// Threshold overrides, applied the way production applies them: a ConfigMap / env change to a
/// POLICY_* value, leaving the policy FILE byte-identical. This is exactly the case that a file
/// hash would miss and a resolved-policy content hash catches (engine §6.2.1 point 2), so
/// building the tightened/relaxed fixtures this way keeps the tests honest about what changed.
/// </summary>
public static class PolicyOverrides
{
    public static Policy WithThreshold(this Policy policy, string name, string value)
    {
        if (!policy.Thresholds.ContainsKey(name))
            throw new InvalidOperationException(
                $"Threshold '{name}' is not defined in the policy. Overriding an undefined " +
                "threshold would silently create a new one and defeat the point of the fixture.");

        var thresholds = new Dictionary<string, string>(policy.Thresholds) { [name] = value };
        return policy with { Thresholds = thresholds };
    }
}
