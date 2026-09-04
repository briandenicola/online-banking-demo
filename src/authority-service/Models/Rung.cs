namespace AuthorityService.Models;

/// <summary>
/// The total order L1 &lt; L2 &lt; L3. Per epic §4.3 and policy-engine §3.4 this is the ONLY
/// ordering in the engine. Both the contextual axis (escalators) and the temporal axis
/// (execution-time re-evaluation, epic §5.3.2) read it. If a second ordering ever appears,
/// the model has diverged.
/// </summary>
public enum Rung
{
    L1 = 1,
    L2 = 2,
    L3 = 3
}

public static class RungOrder
{
    public static readonly IReadOnlyList<Rung> All = [Rung.L1, Rung.L2, Rung.L3];

    /// <summary>
    /// The only combinator in the engine. <c>max</c> over a total order satisfies
    /// <c>max(x, y) &gt;= x</c>, which is what makes invariant I-4 structural rather than
    /// a discipline: firing an escalator can never lower the result.
    /// </summary>
    public static Rung Max(Rung a, Rung? b) => b is null ? a : (a >= b.Value ? a : b.Value);

    /// <summary>
    /// The <c>raiseBy</c> form used by the epic §4.2 policy file. Clamped at L3.
    /// A negative <c>raiseBy</c> is a lowering operator, which I-4 forbids and the grammar
    /// must not admit — so it throws rather than silently clamping.
    /// </summary>
    public static Rung RaiseBy(Rung from, int steps)
    {
        if (steps < 0)
        {
            throw new PolicyValidationException(
                "raiseBy must be >= 0. A negative raiseBy is a lowering operator, which " +
                "invariant I-4 forbids and the policy grammar does not admit.");
        }

        // Computed in long. `(int)from + steps` overflows to a NEGATIVE number for a large
        // steps, and a clamp that only tests the upper bound lets that negative fall through
        // and cast to a rung below L1 — escalation becoming a downgrade by arithmetic, the one
        // outcome invariant I-4 declares structurally impossible. (Livingston, F-9.)
        var target = (long)from + steps;

        return target >= (long)Rung.L3 ? Rung.L3 : (Rung)target;
    }

    public static Rung Parse(string value) => value switch
    {
        "L1" => Rung.L1,
        "L2" => Rung.L2,
        "L3" => Rung.L3,
        _ => throw new PolicyValidationException(
            $"Unknown rung '{value}'. The ladder has exactly three rungs: L1, L2, L3.")
    };

    public static string ToWire(Rung rung) => rung switch
    {
        Rung.L1 => "L1",
        Rung.L2 => "L2",
        Rung.L3 => "L3",
        _ => throw new InvalidOperationException($"Unmapped rung {rung}.")
    };

    /// <summary>Human-facing label used in void/escalation copy (design §3.6).</summary>
    public static string Label(Rung rung) => rung switch
    {
        Rung.L1 => "your signature alone",
        Rung.L2 => "a supervisor co-signature",
        Rung.L3 => "handling outside the Copilot",
        _ => throw new InvalidOperationException($"Unmapped rung {rung}.")
    };
}

/// <summary>Thrown whenever the policy file is missing, malformed, or self-inconsistent. Always fatal at startup.</summary>
public class PolicyValidationException : Exception
{
    public PolicyValidationException(string message) : base(message) { }
    public PolicyValidationException(string message, Exception inner) : base(message, inner) { }
}
