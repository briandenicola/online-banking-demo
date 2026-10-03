using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public interface ITrajectoryEvaluationRepository
{
    Task<TrajectoryEvaluationRecord> CreateAsync(TrajectoryEvaluationRecord record);
    Task<List<TrajectoryEvaluationRecord>> GetAllAsync();
    Task<EscalationConfusionMatrix> GetEscalationConfusionMatrixAsync();
}
