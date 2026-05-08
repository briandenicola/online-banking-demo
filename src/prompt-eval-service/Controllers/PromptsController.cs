using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PromptEvalService.Models;
using PromptEvalService.Services;

namespace PromptEvalService.Controllers;

[ApiController]
[Route("api/evaluations/prompts")]
[Authorize(Roles = "admin,Admin")]
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
