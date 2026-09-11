using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PromptEvalService.Models;
using PromptEvalService.Services;

namespace PromptEvalService.Controllers;

[ApiController]
[Route("api/evaluations/prompts")]
// Class gate: read-only observability. Reading which prompt templates exist is background a
// supervisor needs to interpret an evaluation. Authoring them is configuration, so every write
// below narrows back to admin-only. See the note on EvaluationsController.
[Authorize(Roles = BankingRoles.ObservabilityRead)]
public class PromptsController : ControllerBase
{
    private readonly IPromptTemplateService _templateService;
    private readonly ILogger<PromptsController> _logger;

    public PromptsController(IPromptTemplateService templateService, ILogger<PromptsController> logger)
    {
        _templateService = templateService;
        _logger = logger;
    }

    [HttpGet]
    public async Task<ActionResult<List<PromptTemplate>>> GetAll()
    {
        var templates = await _templateService.GetAllAsync();
        return Ok(templates);
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<PromptTemplate>> GetById(string id)
    {
        var template = await _templateService.GetByIdAsync(id);
        if (template == null) return NotFound();
        return Ok(template);
    }

    // Mutating: creates a prompt template (write config). Admin-only.
    [Authorize(Roles = BankingRoles.Admin)]
    [HttpPost]
    public async Task<ActionResult<PromptTemplate>> Create([FromBody] CreatePromptTemplateRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.Name) || string.IsNullOrWhiteSpace(request.SystemPrompt))
            return BadRequest(new { error = "Name and systemPrompt are required" });

        if (request.Target != "risk-scoring" && request.Target != "categorization")
            return BadRequest(new { error = "Target must be 'risk-scoring' or 'categorization'" });

        var template = new PromptTemplate
        {
            Name = request.Name,
            Description = request.Description,
            Target = request.Target,
            SystemPrompt = request.SystemPrompt,
            UserId = "global"
        };

        var created = await _templateService.CreateAsync(template);
        return CreatedAtAction(nameof(GetById), new { id = created.Id }, created);
    }

    // Mutating: edits a prompt template (write config). Admin-only.
    [Authorize(Roles = BankingRoles.Admin)]
    [HttpPut("{id}")]
    public async Task<ActionResult<PromptTemplate>> Update(string id, [FromBody] UpdatePromptTemplateRequest request)
    {
        try
        {
            var updated = await _templateService.UpdateAsync(id, request);
            return Ok(updated);
        }
        catch (KeyNotFoundException)
        {
            return NotFound();
        }
    }

    // Mutating: deletes a prompt template (write config). Admin-only.
    [Authorize(Roles = BankingRoles.Admin)]
    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(string id)
    {
        try
        {
            await _templateService.DeleteAsync(id);
            return NoContent();
        }
        catch (Microsoft.Azure.Cosmos.CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return NotFound();
        }
    }
}
