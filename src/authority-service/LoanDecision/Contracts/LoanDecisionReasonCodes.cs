namespace AuthorityService.LoanDecision.Contracts;

public static class LoanDecisionReasonCodes
{
    public const string PolicyDefinitionUnresolved = "POLICY_DEFINITION_UNRESOLVED";
    public const string BindingMismatch = "LOAN_BINDING_MISMATCH";
    public const string EvidenceIncomplete = "LOAN_EVIDENCE_INCOMPLETE";
    public const string EvidenceStale = "LOAN_EVIDENCE_STALE";
    public const string EvidenceContradictory = "LOAN_EVIDENCE_CONTRADICTORY";
    public const string DigestMismatch = "LOAN_DIGEST_MISMATCH";
    public const string AuthoritativeSourceUnavailable = "LOAN_AUTHORITATIVE_SOURCE_UNAVAILABLE";
    public const string AuthoritativeSourceChanged = "LOAN_AUTHORITATIVE_SOURCE_CHANGED";
}
