using System;

namespace OnlineBankingDemo.Contracts.Events;

/// <summary>
/// Event published when a user registers
/// </summary>
public class UserRegisteredEvent : IEvent
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string Source { get; set; } = "user-service";
    public string UserId { get; set; } = null!;
    public string Username { get; set; } = null!;
    public string Email { get; set; } = null!;
}