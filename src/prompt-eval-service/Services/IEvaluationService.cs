using PromptEvalService.Models;

namespace PromptEvalService.Services;

public interface IEvaluationService
{
    Task<EvaluationRun> StartEvaluationAsync(string templateId, List<string> transactionIds);
    Task ExecuteFoundryEvaluationAsync(EvaluationRun run, PromptTemplate template, List<TransactionData> transactions, string? bearerToken = null);
    Task<EvaluationRun> ReviewOutputItemAsync(string runId, int itemIndex, string decision, string? notes, string reviewedBy);
    Task<EvaluationRun?> GetRunAsync(string id);
    Task<PaginatedResponse<EvaluationRunSummary>> ListRunsAsync(int page = 1, int pageSize = 20, string? templateId = null);
    Task<ComparisonResponse> CompareRunsAsync(string runId1, string runId2);
}
