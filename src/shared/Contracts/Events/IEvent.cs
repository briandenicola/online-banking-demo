using System;

namespace OnlineBankingDemo.Contracts.Events;

/// <summary>
/// Base event interface
/// </summary>
public interface IEvent
{
    string Id { get; set; }
    DateTime Timestamp { get; set; }
    string Source { get; set; }
}