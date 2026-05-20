namespace LoanOrigination.Repositories;

public interface ICosmosRepository<T> where T : class
{
    Task<T> CreateAsync(T item, string partitionKey);
    Task<T?> GetByIdAsync(string id, string partitionKey);
    Task<List<T>> QueryAsync(string query, Dictionary<string, object> parameters, string? partitionKey = null);
    Task<T> UpsertAsync(T item, string partitionKey);
    Task DeleteAsync(string id, string partitionKey);
}
