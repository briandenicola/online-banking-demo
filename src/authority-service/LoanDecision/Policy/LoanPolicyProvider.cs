namespace AuthorityService.LoanDecision.Policy;

public interface ILoanPolicyProvider
{
    ResolvedLoanPolicy Current { get; }
    ResolvedLoanPolicy RequireExecutable();
}

public sealed class LoanPolicyProvider : ILoanPolicyProvider
{
    public LoanPolicyProvider(ResolvedLoanPolicy policy)
    {
        Current = policy;
    }

    public ResolvedLoanPolicy Current { get; }

    public ResolvedLoanPolicy RequireExecutable()
    {
        throw new LoanPolicyValidationException(
            $"{LoanPolicyLoader.UnresolvedReasonCode}: POL-001..POL-010 are provisional. " +
            "The loan policy engine is dormant and cannot produce a decision.");
    }
}

public static class LoanPolicyServiceCollectionExtensions
{
    public static IServiceCollection AddDormantLoanDecisionPolicy(
        this IServiceCollection services,
        IConfiguration configuration)
    {
        var options = new LoanPolicyOptions
        {
            FilePath = configuration["LOAN_UNDERWRITING_POLICY_FILE_PATH"]
                       ?? configuration["LoanUnderwritingPolicy:FilePath"]
                       ?? string.Empty
        };
        var loader = new LoanPolicyLoader();
        var policy = loader.LoadFromFile(options.FilePath);

        services.AddSingleton(options);
        services.AddSingleton(loader);
        services.AddSingleton<ILoanPolicyProvider>(new LoanPolicyProvider(policy));
        return services;
    }
}
