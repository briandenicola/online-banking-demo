using PromptEvalService.Models;

namespace PromptEvalService.Services;

public interface IPromptTemplateService
{
    Task<List<PromptTemplate>> GetAllAsync();
    Task<PromptTemplate?> GetByIdAsync(string id);
    Task<PromptTemplate> CreateAsync(PromptTemplate template);
    Task<PromptTemplate> UpdateAsync(string id, UpdatePromptTemplateRequest request);
    Task DeleteAsync(string id);
}
