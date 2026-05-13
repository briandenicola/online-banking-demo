using PromptEvalService.Models;
using PromptEvalService.Repositories;

namespace PromptEvalService.Services;

public class PromptTemplateService : IPromptTemplateService
{
    private readonly IPromptTemplateRepository _repository;
    private readonly ILogger<PromptTemplateService> _logger;

    public PromptTemplateService(IPromptTemplateRepository repository, ILogger<PromptTemplateService> logger)
    {
        _repository = repository;
        _logger = logger;
    }

    public async Task<List<PromptTemplate>> GetAllAsync()
    {
        return await _repository.GetAllAsync();
    }

    public async Task<PromptTemplate?> GetByIdAsync(string id)
    {
        return await _repository.GetByIdAsync(id);
    }

    public async Task<PromptTemplate> CreateAsync(PromptTemplate template)
    {
        template.UserId = "global";
        var created = await _repository.CreateAsync(template);
        _logger.LogInformation("Created prompt template {Name} (v{Version}) for user {UserId}", template.Name, template.Version, template.UserId);
        return created;
    }

    public async Task<PromptTemplate> UpdateAsync(string id, UpdatePromptTemplateRequest request)
    {
        var existing = await GetByIdAsync(id)
            ?? throw new KeyNotFoundException($"Template {id} not found");

        if (request.Name != null) existing.Name = request.Name;
        if (request.Description != null) existing.Description = request.Description;
        if (request.SystemPrompt != null) existing.SystemPrompt = request.SystemPrompt;

        existing.Version++;
        existing.UpdatedAt = DateTime.UtcNow;

        var updated = await _repository.ReplaceAsync(id, existing);
        _logger.LogInformation("Updated prompt template {Name} to v{Version}", existing.Name, existing.Version);
        return updated;
    }

    public async Task DeleteAsync(string id)
    {
        await _repository.DeleteAsync(id);
        _logger.LogInformation("Deleted prompt template {Id}", id);
    }
}
