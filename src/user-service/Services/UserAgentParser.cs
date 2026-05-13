namespace UserService.Services;

/// <summary>
/// Stateless helper that maps raw User-Agent header strings to a coarse browser label.
/// Extracted from controllers so detection logic lives in one place.
/// </summary>
public interface IUserAgentParser
{
    string? GetBrowser(string? userAgent);
}

public sealed class UserAgentParser : IUserAgentParser
{
    public string? GetBrowser(string? userAgent)
    {
        if (string.IsNullOrEmpty(userAgent))
        {
            return null;
        }

        if (userAgent.Contains("Edge")) return Constants.Browsers.Edge;
        if (userAgent.Contains("Firefox")) return Constants.Browsers.Firefox;
        if (userAgent.Contains("Chrome")) return Constants.Browsers.Chrome;
        if (userAgent.Contains("Safari")) return Constants.Browsers.Safari;
        return Constants.Browsers.Other;
    }
}
