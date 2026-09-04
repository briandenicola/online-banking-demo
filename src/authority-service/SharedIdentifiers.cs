namespace AuthorityService;

/// <summary>
/// The canonical vocabulary of the Banker Copilot epic (§0.1, NORMATIVE).
///
/// This is the authoritative home for every identifier that appears in more than one of the
/// three Banker Copilot documents. Nothing in this service may restate one of these values as
/// a bare string literal — a mismatch on an action id or a terminal reason is a silent policy
/// miss, not a compile error (epic §5.3.1a).
/// </summary>
public static class SharedIdentifiers
{
    /// <summary>Lifecycle statuses. There is NO <c>expired</c>, NO <c>voided</c>, NO <c>execution_failed</c>.</summary>
    public static class Status
    {
        public const string Proposed = "proposed";
        public const string Pending = "pending";
        public const string Signed = "signed";
        public const string Executed = "executed";
        public const string Denied = "denied";

        public static readonly IReadOnlyList<string> All =
            [Proposed, Pending, Signed, Executed, Denied];
    }

    /// <summary>The closed four-value terminal reason enum (epic §5.1.1b). Exactly four. No others.</summary>
    public static class TerminalReasons
    {
        public const string HumanDenied = "HUMAN_DENIED";
        public const string PolicyRungEscalated = "POLICY_RUNG_ESCALATED";
        public const string PayloadSuperseded = "PAYLOAD_SUPERSEDED";
        public const string TtlExpired = "TTL_EXPIRED";

        public static readonly IReadOnlyList<string> All =
            [HumanDenied, PolicyRungEscalated, PayloadSuperseded, TtlExpired];
    }

    /// <summary>Execution states. Orthogonal to <see cref="Status"/> — see epic §5.1.</summary>
    public static class ExecutionStates
    {
        public const string NotAttempted = "not_attempted";
        public const string InFlight = "in_flight";
        public const string Succeeded = "succeeded";
        public const string Failed = "failed";
    }

    /// <summary>Audit event names — PascalCase, matching the existing <c>banking-events</c> vocabulary (epic §5.7).</summary>
    public static class Events
    {
        public const string ApprovalProposed = "ApprovalProposed";
        public const string ActionProposalRejected = "ActionProposalRejected";
        public const string PolicyEscalated = "PolicyEscalated";
        public const string ApprovalSigned = "ApprovalSigned";
        public const string ApprovalDenied = "ApprovalDenied";
        public const string ApprovalExpired = "ApprovalExpired";
        public const string ApprovalExecuted = "ApprovalExecuted";
        public const string ApprovalExecutionFailed = "ApprovalExecutionFailed";
        public const string ApprovalVoidedByPolicyChange = "ApprovalVoidedByPolicyChange";
        public const string PolicyReloaded = "PolicyReloaded";
        public const string CopilotSessionStarted = "CopilotSessionStarted";

        public static readonly IReadOnlyList<string> All =
        [
            CopilotSessionStarted, ApprovalProposed, ActionProposalRejected, PolicyEscalated,
            ApprovalSigned, ApprovalDenied, ApprovalExpired, ApprovalExecuted,
            ApprovalExecutionFailed, ApprovalVoidedByPolicyChange, PolicyReloaded
        ];
    }

    /// <summary>Document field names on the approval record. One spelling, everywhere.</summary>
    public static class Fields
    {
        public const string RequesterId = "requesterId";
        public const string SupersededByApprovalId = "supersededByApprovalId";
        public const string RequiredRung = "requiredRung";
        public const string BaseRung = "baseRung";
        public const string RequiredSigners = "requiredSigners";
        public const string PayloadHash = "payloadHash";
        public const string PolicyVersion = "policyVersion";
        public const string ExpiresAt = "expiresAt";
        public const string TerminalAt = "terminalAt";
        public const string TerminalReason = "terminalReason";
        public const string ActionId = "actionId";
        public const string FiredEscalators = "firedEscalators";
    }

    /// <summary>Approval id prefix — follows the entity (epic §0.1).</summary>
    public const string ApprovalIdPrefix = "apr_";

    /// <summary>Browser-facing route prefix owned by this service.</summary>
    public const string ApiPrefix = "/api/authority";

    /// <summary>Canonicalization / signing scheme tags (design §6.2, §6.3). Protocol constants, not thresholds.</summary>
    public const string CanonicalizationScheme = "bcp.v2";
    public const string SignatureScheme = "bcp-sig.v2";
    public const int CanonicalizationVersion = 2;
    public const string CanonicalizationLabel = "JCS/RFC-8785";
}
