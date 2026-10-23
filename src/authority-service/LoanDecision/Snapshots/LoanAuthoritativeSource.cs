using AuthorityService.LoanDecision.Contracts;

namespace AuthorityService.LoanDecision.Snapshots;

public interface ILoanAuthoritativeSource
{
    IReadOnlyList<LoanAuthoritativePageV1> Enumerate(LoanAuthoritativeQueryV1 query);
}

public sealed class UnconfiguredLoanAuthoritativeSource : ILoanAuthoritativeSource
{
    public IReadOnlyList<LoanAuthoritativePageV1> Enumerate(LoanAuthoritativeQueryV1 query) =>
        throw new LoanSnapshotValidationException(
            LoanDecisionReasonCodes.AuthoritativeSourceUnavailable,
            "No authoritative loan service is configured. Loan decision control remains dormant.");
}

public sealed class LoanAuthoritativeQueryV1
{
    public required string ApplicantId { get; init; }
    public required string ApplicationId { get; init; }
    public required string ActionId { get; init; }
}

public sealed class LoanAuthoritativePageV1
{
    public required string SourceId { get; init; }
    public required int PageNumber { get; init; }
    public string? RequestToken { get; init; }
    public string? NextToken { get; init; }
    public required LoanSourceBindingV1 Source { get; init; }
    public IReadOnlyList<LoanAuthoritativeRecordV1> Records { get; init; } = [];
}

public sealed class LoanAuthoritativeRecordV1
{
    public LoanDocumentBindingV1? Document { get; init; }
    public LoanEvidenceItemV1? Evidence { get; init; }
    public LoanFreshnessResultV1? Freshness { get; init; }
    public IReadOnlyList<LoanContradictionResultV1> Contradictions { get; init; } = [];
    public IReadOnlyList<LoanNormalizedFactV1> Facts { get; init; } = [];
}
