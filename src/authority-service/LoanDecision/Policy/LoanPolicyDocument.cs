namespace AuthorityService.LoanDecision.Policy;

public sealed class LoanPolicyDocument
{
    public string ApiVersion { get; set; } = string.Empty;
    public LoanPolicyMetadata Metadata { get; set; } = new();
    public List<LoanPolicyRuleDefinition> Rules { get; set; } = [];
}

public sealed class LoanPolicyMetadata
{
    public string PolicyId { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
}

public sealed class LoanPolicyRuleDefinition
{
    public string Id { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public string Operator { get; set; } = string.Empty;
    public string Outcome { get; set; } = string.Empty;
    public string ReasonCode { get; set; } = string.Empty;
}

public sealed class ResolvedLoanPolicy
{
    public required LoanPolicyDocument Document { get; init; }
    public required string PolicyVersion { get; init; }
    public required DateTimeOffset LoadedAt { get; init; }

    public bool IsExecutable => false;
}

public sealed class LoanPolicyOptions
{
    public string FilePath { get; set; } = string.Empty;
}

public sealed class LoanPolicyValidationException : Exception
{
    public LoanPolicyValidationException(string message) : base(message) { }
    public LoanPolicyValidationException(string message, Exception inner) : base(message, inner) { }
}
