namespace BankerCopilotTests.Spec;

/// <summary>
/// The total order L1 &lt; L2 &lt; L3. Per epic §4.3 and policy-engine §3.4 this is the ONLY
/// ordering in the engine; both the contextual axis (escalators) and the temporal axis
/// (execution-time re-evaluation, epic §5.3.2 / engine §3.6) read it.
/// </summary>
public enum Rung
{
    L1 = 1,
    L2 = 2,
    L3 = 3
}

public static class RungOrder
{
    public static readonly Rung[] All = [Rung.L1, Rung.L2, Rung.L3];

    public static Rung Max(Rung a, Rung? b) => b is null ? a : (a >= b.Value ? a : b.Value);

    /// <summary>
    /// The <c>raiseBy</c> form used by the epic's §4.2 policy file. Clamped at L3. A negative
    /// raiseBy is not representable — I-4 says nothing may lower, so the grammar must not admit it.
    /// </summary>
    public static Rung RaiseBy(Rung from, int steps)
    {
        if (steps < 0)
            throw new InvalidOperationException(
                "raiseBy must be >= 0. A negative raiseBy is a lowering operator, which " +
                "invariant I-4 forbids and the grammar must not admit.");

        // Widened deliberately. `(int)from + steps` overflows for steps near int.MaxValue and
        // wraps to a NEGATIVE rung, which the `>= L3` clamp then fails to catch — an escalation
        // that lands below L1. Production has this same shape (finding F-9); the oracle is
        // hardened so that it can act as the reference the production code is compared against.
        long target = (long)from + steps;
        return target >= (long)Rung.L3 ? Rung.L3 : (Rung)target;
    }

    public static Rung Parse(string s) => s switch
    {
        "L1" => Rung.L1,
        "L2" => Rung.L2,
        "L3" => Rung.L3,
        _ => throw new InvalidOperationException(
            $"Unknown rung '{s}'. The ladder has exactly three rungs.")
    };
}
