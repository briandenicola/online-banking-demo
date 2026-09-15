using Microsoft.Azure.Cosmos;
using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public class CosmosTrajectoryEvaluationRepository : ITrajectoryEvaluationRepository
{
    private readonly Container _container;
    private const string DefaultSessionId = "trajectory-eval";

    public CosmosTrajectoryEvaluationRepository(CosmosClient cosmosClient, IConfiguration config)
    {
        var dbName = config["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var containerName = config["CosmosDb:TrajectoryEvaluationsContainerName"] ?? "copilot-trajectory-evals";
        _container = cosmosClient.GetContainer(dbName, containerName);
    }

    public async Task<TrajectoryEvaluationRecord> CreateAsync(TrajectoryEvaluationRecord record)
    {
        var response = await _container.CreateItemAsync(record, new PartitionKey(record.SessionId));
        return response.Resource;
    }

    public async Task<List<TrajectoryEvaluationRecord>> GetAllAsync()
    {
        var query = new QueryDefinition("SELECT * FROM c WHERE c.sessionId = @sessionId")
            .WithParameter("@sessionId", DefaultSessionId);

        var all = new List<TrajectoryEvaluationRecord>();
        using var iterator = _container.GetItemQueryIterator<TrajectoryEvaluationRecord>(query);
        while (iterator.HasMoreResults)
        {
            var response = await iterator.ReadNextAsync();
            all.AddRange(response);
        }

        return all.OrderByDescending(r => r.CreatedAt).ToList();
    }

    public async Task<EscalationConfusionMatrix> GetEscalationConfusionMatrixAsync()
    {
        var records = await GetAllAsync();
        var labels = new[] { "L1", "L2" };
        var matrix = labels.ToDictionary(
            label => label,
            label => labels.ToDictionary(inner => inner, _ => 0));

        var correctPredictions = 0;
        foreach (var record in records)
        {
            var expected = NormalizeRung(record.ExpectedEscalationRung ?? "L1");
            var predicted = NormalizeRung(record.PredictedEscalationRung ?? "L1");
            matrix[expected][predicted] += 1;

            if (expected == predicted)
            {
                correctPredictions++;
            }
        }

        return new EscalationConfusionMatrix
        {
            Labels = labels.ToList(),
            Matrix = matrix,
            Total = records.Count,
            CorrectPredictions = correctPredictions
        };
    }

    private static string NormalizeRung(string rung)
    {
        var normalized = (rung ?? string.Empty).Trim();
        if (string.Equals(normalized, "L1", StringComparison.OrdinalIgnoreCase)) return "L1";
        if (string.Equals(normalized, "L2", StringComparison.OrdinalIgnoreCase)) return "L2";
        return normalized.ToUpperInvariant();
    }
}
