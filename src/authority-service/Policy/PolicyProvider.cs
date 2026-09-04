namespace AuthorityService.Policy;

/// <summary>
/// Holds the currently-active resolved policy. The evaluator reads the CURRENT policy at
/// execution time (design §3.6); signature verification reads the version STORED on the
/// approval (design §6.4). Those two must never share an input, so the distinction lives here:
/// this type only ever hands out the live one.
/// </summary>
public interface IPolicyProvider
{
    ResolvedPolicy Current { get; }

    /// <summary>Swaps in a newly resolved policy and returns the version it replaced.</summary>
    string Swap(ResolvedPolicy policy);
}

public class PolicyProvider : IPolicyProvider
{
    private readonly object _gate = new();
    private ResolvedPolicy _current;

    public PolicyProvider(ResolvedPolicy initial)
    {
        _current = initial;
    }

    public ResolvedPolicy Current
    {
        get
        {
            lock (_gate) return _current;
        }
    }

    public string Swap(ResolvedPolicy policy)
    {
        lock (_gate)
        {
            var previous = _current.PolicyVersion;
            _current = policy;
            return previous;
        }
    }
}
