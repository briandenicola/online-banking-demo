using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public interface IEvaluationRunRepository
{
    Task<EvaluationRun?> GetByIdAsync(string id);
    Task<List<EvaluationRun>> GetAllAsync(string? templateId = null);
    Task<EvaluationRun> CreateAsync(EvaluationRun run);
    Task<EvaluationRun> ReplaceAsync(string id, EvaluationRun run);
}
