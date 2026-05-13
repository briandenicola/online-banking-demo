using PromptEvalService.Models;

namespace PromptEvalService.Repositories;

public interface IPromptTemplateRepository
{
    Task<List<PromptTemplate>> GetAllAsync();
    Task<PromptTemplate?> GetByIdAsync(string id);
    Task<PromptTemplate> CreateAsync(PromptTemplate template);
    Task<PromptTemplate> ReplaceAsync(string id, PromptTemplate template);
    Task DeleteAsync(string id);
}
