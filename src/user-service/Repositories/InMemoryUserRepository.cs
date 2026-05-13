using System.Collections.Concurrent;
using UserModel = UserService.Models.User;

namespace UserService.Repositories;

/// <summary>
/// In-memory <see cref="IUserRepository"/> for development / test runs.
/// Storage adapter only — business logic lives in <see cref="Services.UserService"/>.
/// </summary>
public class InMemoryUserRepository : IUserRepository
{
    private readonly ConcurrentDictionary<string, UserModel> _users = new();
    private readonly ConcurrentDictionary<string, string> _emailIndex =
        new(StringComparer.OrdinalIgnoreCase);

    public void Seed(UserModel user)
    {
        _users[user.Id] = user;
        _emailIndex[user.Email] = user.Id;
    }

    public Task<UserModel?> GetByIdAsync(string id)
    {
        _users.TryGetValue(id, out var user);
        return Task.FromResult<UserModel?>(user);
    }

    public Task<UserModel?> GetByUsernameAsync(string username)
    {
        var user = _users.Values.FirstOrDefault(
            u => u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));
        return Task.FromResult<UserModel?>(user);
    }

    public Task<UserModel?> GetByEmailAsync(string email)
    {
        var user = _users.Values.FirstOrDefault(
            u => u.Email.Equals(email, StringComparison.OrdinalIgnoreCase));
        return Task.FromResult<UserModel?>(user);
    }

    public Task<UserModel> CreateAsync(UserModel user)
    {
        _users[user.Id] = user;
        _emailIndex[user.Email] = user.Id;
        return Task.FromResult(user);
    }

    public Task<UserModel> ReplaceAsync(UserModel user)
    {
        _users[user.Id] = user;
        return Task.FromResult(user);
    }

    public Task<bool> DeleteAsync(string id)
    {
        if (_users.TryRemove(id, out var user))
        {
            _emailIndex.TryRemove(user.Email, out _);
            return Task.FromResult(true);
        }
        return Task.FromResult(false);
    }

    public Task<bool> IsContainerEmptyAsync()
    {
        return Task.FromResult(_users.IsEmpty);
    }

    public Task<int> GetAdminCountAsync()
    {
        var count = _users.Values.Count(u => u.Role == Constants.Roles.Admin);
        return Task.FromResult(count);
    }

    public Task<List<UserModel>> GetAllUsersAsync()
    {
        return Task.FromResult(_users.Values.ToList());
    }

    public Task CreateEmailLookupAsync(string emailLookupId, object emailLookupDoc)
    {
        // Email uniqueness is enforced by GetByEmailAsync against _users; the
        // separate lookup document used by Cosmos to prevent TOCTOU races is
        // not needed for the in-memory dictionary which is naturally atomic.
        return Task.CompletedTask;
    }

    public Task DeleteEmailLookupAsync(string emailLookupId) => Task.CompletedTask;
}
