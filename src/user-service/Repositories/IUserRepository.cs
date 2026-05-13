namespace UserService.Repositories;

public interface IUserRepository
{
    Task<Models.User?> GetByIdAsync(string id);
    Task<Models.User?> GetByUsernameAsync(string username);
    Task<Models.User?> GetByEmailAsync(string email);
    Task<Models.User> CreateAsync(Models.User user);
    Task<Models.User> ReplaceAsync(Models.User user);
    Task<bool> DeleteAsync(string id);
    Task<bool> IsContainerEmptyAsync();
    Task<int> GetAdminCountAsync();
    Task<List<Models.User>> GetAllUsersAsync();
    Task CreateEmailLookupAsync(string emailLookupId, object emailLookupDoc);
    Task DeleteEmailLookupAsync(string emailLookupId);
}
