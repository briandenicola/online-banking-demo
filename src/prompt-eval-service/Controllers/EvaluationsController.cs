using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PromptEvalService.Models;
using PromptEvalService.Services;

namespace PromptEvalService.Controllers;

[ApiController]
[Route("api/evaluations")]
[Authorize(Roles = "admin,Admin")]
public class EvaluationsController : ControllerBase
{
    private readonly IEvaluationService _evalService;
    private readonly ILogger<EvaluationsController> _logger;

    public EvaluationsController(IEvaluationService evalService, ILogger<EvaluationsController> logger)
    {
        _evalService = evalService;
        _logger = logger;
    }

    [HttpPost("run")]
    public async Task<ActionResult<EvaluationRun>> RunEvaluation([FromBody] RunEvaluationRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.TemplateId))
            return BadRequest(new { error = "TemplateId is required" });

        if (request.TransactionIds.Count == 0)
            return BadRequest(new { error = "At least one transaction ID is required" });

        try
        {
            var run = await _evalService.StartEvaluationAsync(request.TemplateId, request.TransactionIds);
            return AcceptedAtAction(nameof(GetRun), new { id = run.Id }, run);
        }
        catch (KeyNotFoundException ex)
        {
            return NotFound(new { error = ex.Message });
        }
    }

    [HttpGet]
    public async Task<ActionResult<PaginatedResponse<EvaluationRunSummary>>> ListRuns(
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 20,
        [FromQuery] string? templateId = null)
    {
        var result = await _evalService.ListRunsAsync(page, pageSize, templateId);
        return Ok(result);
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<EvaluationRun>> GetRun(string id)
    {
        var run = await _evalService.GetRunAsync(id);
        if (run == null) return NotFound();
        return Ok(run);
    }

    [HttpGet("compare")]
    public async Task<ActionResult<ComparisonResponse>> CompareRuns(
        [FromQuery] string runId1,
        [FromQuery] string runId2)
    {
        try
        {
            var comparison = await _evalService.CompareRunsAsync(runId1, runId2);
            return Ok(comparison);
        }
        catch (KeyNotFoundException ex)
        {
            return NotFound(new { error = ex.Message });
        }
    }
}
