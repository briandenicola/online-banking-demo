using PromptEvalService.Models;

namespace PromptEvalService.Services;

public interface ITrajectoryScorer
{
    Task<TrajectoryEvaluationRecord> ScoreFixtureAsync(string traceFilePath, string expectedFilePath, string? scenarioName = null);
    Task<TrajectoryEvaluationRecord> ScoreFixtureDirectoryAsync(string? fixtureRoot = null);
    Task<EscalationConfusionMatrix> GetEscalationConfusionMatrixAsync();
}
