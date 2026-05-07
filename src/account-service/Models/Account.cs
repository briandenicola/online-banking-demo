using System;
using Newtonsoft.Json;

namespace AccountService.Models;

/// <summary>
/// Account model
/// </summary>
public class Account
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string UserId { get; set; } = null!;
    public string AccountNumber { get; set; } = null!;
    public string AccountType { get; set; } = null!;
    public decimal Balance { get; set; }
    public string Currency { get; set; } = "USD";
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public bool IsActive { get; set; } = true;
}