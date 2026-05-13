using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using StackExchange.Redis;
using TransferService.Models;
using TransferService.Repositories;

namespace TransferService.Services;

/// <summary>
/// Publishes domain events for the transfer flow to the eventing layer
/// (Redis stream). Failures are logged but never propagate — eventing is
/// best-effort and must not fail the user-facing transfer.
/// </summary>
public interface ITransferEventPublisher
{
    Task PublishTransferInitiatedAsync(Transfer transfer);
}

public sealed class TransferEventPublisher : ITransferEventPublisher
{
    private const string StreamName = global::TransferService.Constants.DefaultStreamName;

    private readonly IEventPublisher _eventPublisher;
    private readonly ILogger<TransferEventPublisher> _logger;

    public TransferEventPublisher(IEventPublisher eventPublisher, ILogger<TransferEventPublisher> logger)
    {
        _eventPublisher = eventPublisher;
        _logger = logger;
    }

    public async Task PublishTransferInitiatedAsync(Transfer transfer)
    {
        try
        {
            var eventPayload = new
            {
                eventType = global::TransferService.Constants.EventTypes.TransferInitiated,
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    fromAccountId = transfer.FromAccountId,
                    toAccountId = transfer.ToAccountId,
                    amount = transfer.Amount,
                    description = transfer.Description
                }
            };

            await _eventPublisher.PublishAsync(StreamName, JsonConvert.SerializeObject(eventPayload));

            _logger.LogInformation("Published TransferInitiated event to Redis for transfer {TransferId}", transfer.Id);
        }
        catch (RedisConnectionException ex)
        {
            _logger.LogError(ex, "Redis connection failed while publishing TransferInitiated event for transfer {TransferId}", transfer.Id);
        }
        catch (RedisException ex)
        {
            _logger.LogError(ex, "Redis error while publishing TransferInitiated event for transfer {TransferId}", transfer.Id);
        }
    }
}
