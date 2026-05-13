using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using TransferService.Models;
using TransferService.Repositories;

namespace TransferService.Services;

/// <summary>
/// Thin orchestrator: validates the request, executes the side effects,
/// persists the result, and publishes the domain event. All real work
/// lives in the injected collaborators.
/// </summary>
public class TransferService : ITransferService
{
    private readonly ITransferValidator _validator;
    private readonly ITransferExecutor _executor;
    private readonly ITransferEventPublisher _eventPublisher;
    private readonly ITransferRepository _transferRepository;
    private readonly ILogger<TransferService> _logger;

    public TransferService(
        ITransferValidator validator,
        ITransferExecutor executor,
        ITransferEventPublisher eventPublisher,
        ITransferRepository transferRepository,
        ILogger<TransferService> logger)
    {
        _validator = validator;
        _executor = executor;
        _eventPublisher = eventPublisher;
        _transferRepository = transferRepository;
        _logger = logger;
    }

    public async Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request)
    {
        await _validator.ValidateAsync(userId, request);

        var transfer = new Transfer
        {
            Id = Guid.NewGuid().ToString(),
            UserId = userId,
            FromAccountId = request.FromAccountId,
            ToAccountId = request.ToAccountId,
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description,
            Status = global::TransferService.Constants.TransferStatuses.Processing
        };

        try
        {
            await _executor.ExecuteAsync(transfer, request);

            transfer.Status = global::TransferService.Constants.TransferStatuses.Completed;
            transfer.CompletedAt = DateTime.UtcNow;

            await _transferRepository.CreateAsync(transfer);
            await _eventPublisher.PublishTransferInitiatedAsync(transfer);

            return transfer;
        }
        catch (HttpRequestException ex)
        {
            return await PersistFailureAsync(transfer, ex,
                global::TransferService.Constants.FailureReasons.ServiceCommunication,
                "HTTP request failed during transfer: {TransferId}");
        }
        catch (InvalidOperationException ex)
        {
            return await PersistFailureAsync(transfer, ex,
                global::TransferService.Constants.FailureReasons.Generic,
                "Transfer operation failed: {TransferId}");
        }
        catch (CosmosException ex)
        {
            return await PersistFailureAsync(transfer, ex,
                global::TransferService.Constants.FailureReasons.Storage,
                "Cosmos DB error during transfer: {TransferId}");
        }
    }

    public async Task<Transfer?> GetTransferByIdAsync(string id)
    {
        return await _transferRepository.GetByIdAsync(id);
    }

    private async Task<Transfer> PersistFailureAsync(Transfer transfer, Exception ex, string failureReason, string errorTemplate)
    {
        _logger.LogError(ex, errorTemplate, transfer.Id);
        transfer.Status = global::TransferService.Constants.TransferStatuses.Failed;
        transfer.FailureReason = failureReason;
        try
        {
            await _transferRepository.CreateAsync(transfer);
        }
        catch (CosmosException persistEx)
        {
            _logger.LogError(persistEx, "Failed to persist failed transfer record: {TransferId}", transfer.Id);
        }
        return transfer;
    }
}
