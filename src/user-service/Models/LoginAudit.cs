using System;
using Newtonsoft.Json;

namespace UserService.Models;

/// <summary>
/// Login audit record for tracking user authentication events
/// </summary>
public class LoginAudit
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    public string UserId { get; set; } = null!;
    public string Username { get; set; } = null!;
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string IpAddress { get; set; } = null!;
    public string? Geolocation { get; set; }
    public string? Browser { get; set; }
    public string? UserAgent { get; set; }
    public bool Success { get; set; } = true;
    public string? FailureReason { get; set; }
}
