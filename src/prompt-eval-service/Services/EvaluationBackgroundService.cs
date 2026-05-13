using System.Threading.Channels;
using PromptEvalService.Models;
using PromptEvalService.Repositories;

namespace PromptEvalService.Services;

public record EvaluationWorkItem(EvaluationRun Run, PromptTemplate Template, List<TransactionData> Transactions);

public class EvaluationQueue
{
    private readonly Channel<EvaluationWorkItem> _channel = Channel.CreateBounded<EvaluationWorkItem>(
        new BoundedChannelOptions(100)
        {
            FullMode = BoundedChannelFullMode.Wait
        });

    public ChannelWriter<EvaluationWorkItem> Writer => _channel.Writer;
    public ChannelReader<EvaluationWorkItem> Reader => _channel.Reader;
}

public class EvaluationBackgroundService : BackgroundService
{
    private readonly EvaluationQueue _queue;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<EvaluationBackgroundService> _logger;

    public EvaluationBackgroundService(
        EvaluationQueue queue,
        IServiceScopeFactory scopeFactory,
        ILogger<EvaluationBackgroundService> logger)
    {
        _queue = queue;
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("EvaluationBackgroundService started");

        await foreach (var workItem in _queue.Reader.ReadAllAsync(stoppingToken))
        {
            try
            {
                await ProcessEvaluationAsync(workItem, stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unhandled error processing evaluation run {RunId}", workItem.Run.Id);
                await TryMarkRunFailed(workItem.Run, ex);
            }
        }

        _logger.LogInformation("EvaluationBackgroundService stopped");
    }

    private async Task ProcessEvaluationAsync(EvaluationWorkItem workItem, CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var evaluationService = scope.ServiceProvider.GetRequiredService<IEvaluationService>();

        if (evaluationService is EvaluationService svc)
        {
            await svc.ExecuteFoundryEvaluationAsync(workItem.Run, workItem.Template, workItem.Transactions);
        }
    }

    private async Task TryMarkRunFailed(EvaluationRun run, Exception ex)
    {
        try
        {
            using var scope = _scopeFactory.CreateScope();
            var runRepository = scope.ServiceProvider.GetRequiredService<IEvaluationRunRepository>();

            run.Status = "failed";
            run.Error = ex.Message;
            run.CompletedAt = DateTime.UtcNow;
            await runRepository.ReplaceAsync(run.Id, run);
        }
        catch (Exception persistEx)
        {
            _logger.LogError(persistEx, "Failed to mark evaluation run {RunId} as failed", run.Id);
        }
    }
}
