using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PromptEvalService.Models;
using PromptEvalService.Repositories;
using PromptEvalService.Services;

namespace PromptEvalService.Controllers;

[ApiController]
[Route("api/trajectory-eval")]
[Authorize(Roles = BankingRoles.ObservabilityRead)]
public class TrajectoryEvalController : ControllerBase
{
    private readonly ITrajectoryScorer _trajectoryScorer;
    private readonly ITrajectoryEvaluationRepository _trajectoryEvaluationRepository;

    public TrajectoryEvalController(ITrajectoryScorer trajectoryScorer, ITrajectoryEvaluationRepository trajectoryEvaluationRepository)
    {
        _trajectoryScorer = trajectoryScorer;
        _trajectoryEvaluationRepository = trajectoryEvaluationRepository;
    }

    [Authorize(Roles = BankingRoles.Admin)]
    [HttpPost("run")]
    public async Task<ActionResult<TrajectoryEvaluationRecord>> RunTrajectoryEvaluation([FromBody] RunTrajectoryEvaluationRequest? request)
    {
        var fixtureRoot = string.IsNullOrWhiteSpace(request?.FixtureRoot) ? null : request.FixtureRoot;
        var result = await _trajectoryScorer.ScoreFixtureDirectoryAsync(fixtureRoot);
        return Accepted(result);
    }

    [HttpGet("confusion-matrix")]
    public async Task<ActionResult<EscalationConfusionMatrix>> GetConfusionMatrix()
    {
        var matrix = await _trajectoryEvaluationRepository.GetEscalationConfusionMatrixAsync();
        return Ok(matrix);
    }
}
