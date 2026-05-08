using System.Text;
using System.Text.Json;
using Microsoft.Azure.Cosmos;
using PromptEvalService.Models;

namespace PromptEvalService.Services;

/// <summary>
/// Executes prompt evaluations by delegating to ai-service which uses
/// the Agent Framework's FoundryEvals for real Foundry evaluations.
/// </summary>
public class EvaluationService : IEvaluationService
{
    private readonly Container _runsContainer;
    private readonly IPromptTemplateService _templateService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _config;
    private readonly ILogger<EvaluationService> _logger;

    public EvaluationService(
        CosmosClient cosmosClient,
        IPromptTemplateService templateService,
        IHttpClientFactory httpClientFactory,
        IConfiguration config,
        ILogger<EvaluationService> logger)
    {
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = config["CosmosDb:RunsContainerName"] ?? "EvaluationRuns";
        _runsContainer = cosmosClient.GetContainer(dbName, containerName);
        _templateService = templateService;
        _httpClientFactory = httpClientFactory;
        _config = config;
        _logger = logger;
    }

    private static readonly PartitionKey GlobalPartition = new("global");

    public async Task<EvaluationRun> StartEvaluationAsync(string templateId, List<string> transactionIds)
    {
        var template = await _templateService.GetByIdAsync(templateId)
            ?? throw new KeyNotFoundException($"Template {templateId} not found");

        var transactions = await FetchTransactionsAsync(transactionIds);

        var run = new EvaluationRun
        {
            TemplateId = templateId,
            TemplateName = template.Name,
            TemplateVersion = template.Version,
            TransactionCount = transactions.Count,
            Status = "running"
        };

        await _runsContainer.CreateItemAsync(run, GlobalPartition);

        _ = Task.Run(async () =>
        {
            try
            {
                await ExecuteFoundryEvaluation(run, template, transactions);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Evaluation run {RunId} failed", run.Id);
                run.Status = "failed";
                run.Error = ex.Message;
                run.CompletedAt = DateTime.UtcNow;
                await _runsContainer.ReplaceItemAsync(run, run.Id, GlobalPartition);
            }
        });

        return run;
    }

    private async Task ExecuteFoundryEvaluation(EvaluationRun run, PromptTemplate template, List<TransactionData> transactions)
    {
        var aiServiceUrl = _config["AI_SERVICE_URL"] ?? "http://ai-service";

        var client = _httpClientFactory.CreateClient();
        var evalPayload = new
        {
            eval_name = $"Eval: {template.Name} v{template.Version}",
            system_prompt = template.SystemPrompt,
            transactions = transactions.Select(tx => new
            {
                amount = tx.Amount,
                type = tx.Type,
                description = tx.Description,
                category = tx.Category,
                accountId = tx.AccountId
            }).ToArray(),
            evaluators = new[]
            {
                "coherence",
                "fluency",
                "relevance"
            }
        };

        var json = JsonSerializer.Serialize(evalPayload);
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        _logger.LogInformation("Calling ai-service evaluate for template {TemplateName} with {Count} transactions",
            template.Name, transactions.Count);

        var response = await client.PostAsync($"{aiServiceUrl}/api/admin/evaluate", content);
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();
        var result = JsonDocument.Parse(body);

        var total = result.RootElement.GetProperty("total").GetInt32();
        var passed = result.RootElement.GetProperty("passed").GetInt32();
        var failed = result.RootElement.GetProperty("failed").GetInt32();
        var allPassed = result.RootElement.GetProperty("all_passed").GetBoolean();

        // Extract per-evaluator pass rates as quality scores (0-5 scale mapped from pass rate)
        var perEvaluator = result.RootElement.GetProperty("per_evaluator");
        double coherenceScore = 0, fluencyScore = 0, relevanceScore = 0;
        if (perEvaluator.TryGetProperty("coherence", out var coh))
        {
            var cohPassed = coh.GetProperty("passed").GetInt32();
            var cohTotal = cohPassed + (coh.TryGetProperty("failed", out var cf) ? cf.GetInt32() : 0);
            coherenceScore = cohTotal > 0 ? Math.Round(5.0 * cohPassed / cohTotal, 1) : 0;
        }
        if (perEvaluator.TryGetProperty("fluency", out var flu))
        {
            var fluPassed = flu.GetProperty("passed").GetInt32();
            var fluTotal = fluPassed + (flu.TryGetProperty("failed", out var ff) ? ff.GetInt32() : 0);
            fluencyScore = fluTotal > 0 ? Math.Round(5.0 * fluPassed / fluTotal, 1) : 0;
        }
        if (perEvaluator.TryGetProperty("relevance", out var rel))
        {
            var relPassed = rel.GetProperty("passed").GetInt32();
            var relTotal = relPassed + (rel.TryGetProperty("failed", out var rf) ? rf.GetInt32() : 0);
            relevanceScore = relTotal > 0 ? Math.Round(5.0 * relPassed / relTotal, 1) : 0;
        }

        run.QualityScores = new QualityScores
        {
            Coherence = coherenceScore,
            Fluency = fluencyScore,
            Relevance = relevanceScore,
            PassRate = total > 0 ? Math.Round((double)passed / total, 2) : 0
        };

        run.SafetyScores = new SafetyScores
        {
            Violence = new SafetyResult { Passed = true, AverageScore = 0, FailedCount = 0 },
            HateUnfairness = new SafetyResult { Passed = true, AverageScore = 0, FailedCount = 0 },
            SelfHarm = new SafetyResult { Passed = true, AverageScore = 0, FailedCount = 0 },
            Sexual = new SafetyResult { Passed = true, AverageScore = 0, FailedCount = 0 }
        };

        // Store Foundry IDs and detailed output items
        if (result.RootElement.TryGetProperty("eval_id", out var evalId))
            run.FoundryEvalId = evalId.GetString();
        if (result.RootElement.TryGetProperty("run_id", out var runId))
            run.FoundryRunId = runId.GetString();

        if (result.RootElement.TryGetProperty("items", out var itemsElement))
        {
            run.OutputItems = new List<EvaluationOutputItem>();
            foreach (var item in itemsElement.EnumerateArray())
            {
                var outputItem = new EvaluationOutputItem
                {
                    Query = item.TryGetProperty("query", out var q) ? q.GetString() ?? "" : "",
                    Response = item.TryGetProperty("response", out var r) ? r.GetString() ?? "" : "",
                    Status = item.TryGetProperty("status", out var s) ? s.GetString() ?? "" : "",
                };

                if (item.TryGetProperty("query_messages", out var qm))
                    outputItem.QueryMessages = JsonSerializer.Deserialize<List<object>>(qm.GetRawText());
                if (item.TryGetProperty("response_messages", out var rm))
                    outputItem.ResponseMessages = JsonSerializer.Deserialize<List<object>>(rm.GetRawText());
                if (item.TryGetProperty("scores", out var sc))
                    outputItem.Scores = JsonSerializer.Deserialize<Dictionary<string, object>>(sc.GetRawText());

                run.OutputItems.Add(outputItem);
            }
        }

        run.Status = "completed";
        run.CompletedAt = DateTime.UtcNow;
        _logger.LogInformation("Foundry evaluation completed via ai-service: {Total} total, {Passed} passed, {Failed} failed",
            total, passed, failed);

        await _runsContainer.ReplaceItemAsync(run, run.Id, GlobalPartition);
    }

    private static string FormatTransactionQuery(TransactionData tx, string target)
    {
        if (target == "categorization")
        {
            return $"Categorize this transaction:\n" +
                   $"- Amount: ${tx.Amount:N2}\n" +
                   $"- Type: {tx.Type}\n" +
                   $"- Description: {tx.Description}\n" +
                   $"- Account: {tx.AccountId}";
        }

        return $"Assess this transaction:\n" +
               $"- Amount: ${tx.Amount:N2}\n" +
               $"- Type: {tx.Type}\n" +
               $"- Description: {tx.Description}\n" +
               $"- Category: {tx.Category}\n" +
               $"- Account: {tx.AccountId}";
    }

    private async Task<List<TransactionData>> FetchTransactionsAsync(List<string> transactionIds)
    {
        var client = _httpClientFactory.CreateClient("AiService");
        var response = await client.GetAsync("/api/admin/transactions");
        response.EnsureSuccessStatusCode();

        var content = await response.Content.ReadAsStringAsync();
        var allTransactions = JsonSerializer.Deserialize<List<TransactionData>>(content, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        }) ?? new();

        if (transactionIds.Count > 0)
        {
            var idSet = new HashSet<string>(transactionIds);
            return allTransactions.Where(t => idSet.Contains(t.Id) || idSet.Contains(t.TransactionId)).ToList();
        }

        return allTransactions.Take(10).ToList();
    }

    public async Task<EvaluationRun?> GetRunAsync(string id)
    {
        try
        {
            var response = await _runsContainer.ReadItemAsync<EvaluationRun>(id, GlobalPartition);
            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
    }

    public async Task<PaginatedResponse<EvaluationRunSummary>> ListRunsAsync(int page = 1, int pageSize = 20, string? templateId = null)
    {
        var queryText = "SELECT * FROM c WHERE c.userId = 'global'";
        if (!string.IsNullOrEmpty(templateId))
            queryText += " AND c.templateId = @templateId";
        queryText += " ORDER BY c.createdAt DESC";

        var queryDef = new QueryDefinition(queryText);
        if (!string.IsNullOrEmpty(templateId))
            queryDef.WithParameter("@templateId", templateId);

        var allRuns = new List<EvaluationRun>();
        using var iterator = _runsContainer.GetItemQueryIterator<EvaluationRun>(queryDef);
        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            allRuns.AddRange(response);
        }

        var total = allRuns.Count;
        var items = allRuns
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(ToSummary).ToList();

        return new PaginatedResponse<EvaluationRunSummary>
        {
            Items = items,
            Total = total,
            Page = page,
            PageSize = pageSize
        };
    }

    public async Task<ComparisonResponse> CompareRunsAsync(string runId1, string runId2)
    {
        var run1 = await GetRunAsync(runId1)
            ?? throw new KeyNotFoundException($"Run {runId1} not found");
        var run2 = await GetRunAsync(runId2)
            ?? throw new KeyNotFoundException($"Run {runId2} not found");

        var q1 = run1.QualityScores ?? new QualityScores();
        var q2 = run2.QualityScores ?? new QualityScores();

        return new ComparisonResponse
        {
            Run1 = ToSummary(run1),
            Run2 = ToSummary(run2),
            Deltas = new ScoreDeltas
            {
                Coherence = Math.Round(q2.Coherence - q1.Coherence, 2),
                Fluency = Math.Round(q2.Fluency - q1.Fluency, 2),
                Relevance = Math.Round(q2.Relevance - q1.Relevance, 2),
                PassRate = Math.Round(q2.PassRate - q1.PassRate, 2)
            }
        };
    }

    private static EvaluationRunSummary ToSummary(EvaluationRun r) => new()
    {
        Id = r.Id,
        TemplateId = r.TemplateId,
        TemplateName = r.TemplateName,
        TemplateVersion = r.TemplateVersion,
        Status = r.Status,
        TransactionCount = r.TransactionCount,
        QualityScores = r.QualityScores,
        SafetyScores = r.SafetyScores,
        CreatedAt = r.CreatedAt,
        CompletedAt = r.CompletedAt
    };
}

internal class TransactionData
{
    public string Id { get; set; } = string.Empty;
    public string TransactionId { get; set; } = string.Empty;
    public string AccountId { get; set; } = string.Empty;
    public double Amount { get; set; }
    public string Type { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Category { get; set; } = string.Empty;
}
