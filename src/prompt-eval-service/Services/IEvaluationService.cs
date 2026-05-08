using PromptEvalService.Models;

namespace PromptEvalService.Services;

public interface IEvaluationService
{
    Task<EvaluationRun> StartEvaluationAsync(string templateId, List<string> transactionIds);
    Task<EvaluationRun?> GetRunAsync(string id);
    Task<PaginatedResponse<EvaluationRunSummary>> ListRunsAsync(int page = 1, int pageSize = 20, string? templateId = null);
    Task<ComparisonResponse> CompareRunsAsync(string runId1, string runId2);
}
