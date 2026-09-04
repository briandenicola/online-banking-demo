namespace AuthorityService.Services;

/// <summary>
/// A refusal the API surfaces to the caller verbatim. Carries its own HTTP status so the
/// controllers stay thin and every refusal reason is written once, next to the rule it enforces.
/// </summary>
public class AuthorityException : Exception
{
    public AuthorityException(string code, string message, int statusCode = 400, object? data = null)
        : base(message)
    {
        Code = code;
        StatusCode = statusCode;
        Data2 = data;
    }

    public string Code { get; }
    public int StatusCode { get; }
    public object? Data2 { get; }
}
