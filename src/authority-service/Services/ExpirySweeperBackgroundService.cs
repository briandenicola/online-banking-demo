using AuthorityService.Repositories;

namespace AuthorityService.Services;

/// <summary>
/// Sweeps pending approvals past their TTL and DENIES them.
///
/// Native Cosmos TTL is deliberately not the mechanism: TTL deletes the document, and a deleted
/// approval is indistinguishable from one that never existed. "Nobody answered in time" is an
/// audit fact worth keeping, so the sweeper writes <c>denied</c> + <c>TTL_EXPIRED</c> and only
/// then arms the retention TTL (design §5.4).
///
/// The read-side lazy expiry in <see cref="ApprovalService"/> is the actual safety control; this
/// loop exists so the record becomes terminal even if nobody ever reads it again.
/// </summary>
public class ExpirySweeperBackgroundService : BackgroundService
{
    private readonly IServiceProvider _services;
    private readonly IConfiguration _configuration;
    private readonly ILogger<ExpirySweeperBackgroundService> _logger;

    public ExpirySweeperBackgroundService(
        IServiceProvider services,
        IConfiguration configuration,
        ILogger<ExpirySweeperBackgroundService> logger)
    {
        _services = services;
        _configuration = configuration;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = TimeSpan.FromSeconds(
            _configuration.GetValue<int?>("Approval:SweepIntervalSeconds")
            ?? throw new InvalidOperationException(
                "Approval__SweepIntervalSeconds is not configured. Refusing to start with an " +
                "invented sweep cadence."));

        var batchSize = _configuration.GetValue<int?>("Approval:SweepBatchSize")
                        ?? throw new InvalidOperationException(
                            "Approval__SweepBatchSize is not configured.");

        _logger.LogInformation(
            "Approval expiry sweeper started; interval {Interval}, batch {Batch}", interval, batchSize);

        using var timer = new PeriodicTimer(interval);

        while (await timer.WaitForNextTickAsync(stoppingToken))
        {
            try
            {
                await SweepAsync(batchSize, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Approval expiry sweep failed; will retry on the next tick");
            }
        }
    }

    internal async Task<int> SweepAsync(int batchSize, CancellationToken ct)
    {
        using var scope = _services.CreateScope();

        var repository = scope.ServiceProvider.GetRequiredService<IApprovalRepository>();
        var approvals = scope.ServiceProvider.GetRequiredService<ApprovalService>();

        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var expired = await repository.FindExpiredAsync(now, batchSize, ct);
        var swept = 0;

        foreach (var approval in expired)
        {
            try
            {
                await approvals.ExpireAsync(approval, ct);
                swept++;
            }
            catch (ApprovalConcurrencyException)
            {
                // Someone signed or denied it between the query and the write. Their decision
                // wins; the sweeper is not in a race it needs to win.
                _logger.LogDebug("Approval {ApprovalId} changed during the sweep; skipping", approval.Id);
            }
            catch (ApprovalWriteGuardException ex)
            {
                _logger.LogWarning(ex, "Approval {ApprovalId} could not be expired", approval.Id);
            }
        }

        if (swept > 0)
        {
            _logger.LogInformation("Expiry sweep denied {Count} approval(s) with TTL_EXPIRED", swept);
        }

        return swept;
    }
}
