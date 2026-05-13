namespace UserService.Repositories;

public interface ILoginAuditRepository
{
    Task CreateAsync(Models.LoginAudit audit);
    Task<List<Models.LoginAudit>> GetRecentAsync(int limit = 100);
}
