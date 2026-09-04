using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Models;

/// <summary>
/// The durable approval record — "the request for human authorization" (epic §0.1).
/// Container <c>copilot-approvals</c>, partition key <c>/requesterId</c>.
///
/// Property names are pinned explicitly to camelCase rather than relying on a serializer
/// naming policy: this document is written by .NET and read by Python, Cosmos SQL field paths
/// are case-sensitive, and a casing mismatch returns zero rows rather than an error.
///
/// Nothing outside <c>Repositories</c> may write an instance of this type to Cosmos. All
/// mutations funnel through the single-writer repository (design §5.3.1, enforcement layer 2).
/// </summary>
public class Approval
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>PARTITION KEY. The acting banker. Never <c>actorId</c> (epic §0.1).</summary>
    [JsonProperty("requesterId")]
    public string RequesterId { get; set; } = string.Empty;

    [JsonProperty("requesterUsername")]
    public string? RequesterUsername { get; set; }

    [JsonProperty("docType")]
    public string DocType { get; set; } = "approval";

    [JsonProperty("status")]
    [JsonConverter(typeof(ThrowingApprovalStatusConverter))]
    public ApprovalStatus Status { get; set; } = ApprovalStatus.Proposed;

    [JsonProperty("actionId")]
    public string ActionId { get; set; } = string.Empty;

    [JsonProperty("actionLabel")]
    public string ActionLabel { get; set; } = string.Empty;

    [JsonProperty("sessionId")]
    public string? SessionId { get; set; }

    [JsonProperty("agentId")]
    public string? AgentId { get; set; }

    [JsonProperty("correlationId")]
    public string? CorrelationId { get; set; }

    [JsonProperty("target")]
    public ApprovalTarget Target { get; set; } = new();

    [JsonProperty("payload")]
    public JObject Payload { get; set; } = new();

    [JsonProperty("payloadHash")]
    public string PayloadHash { get; set; } = string.Empty;

    /// <summary>
    /// The hash field list AS IT WAS at proposal. Stored on the document rather than re-read
    /// from the live policy so the hash stays recomputable even if the policy file later
    /// changes which fields are covered.
    /// </summary>
    [JsonProperty("hashFields")]
    public List<string> HashFields { get; set; } = [];

    /// <summary>The money field list as it was at proposal. Same reasoning as <see cref="HashFields"/>.</summary>
    [JsonProperty("moneyFields")]
    public List<string> MoneyFields { get; set; } = [];

    /// <summary>The currency scale in force at proposal, frozen for the same reason.</summary>
    [JsonProperty("currencyScale")]
    public int CurrencyScale { get; set; } = 2;

    [JsonProperty("canonicalization")]
    public string Canonicalization { get; set; } = SharedIdentifiers.CanonicalizationLabel;

    [JsonProperty("canonicalizationVersion")]
    public int CanonicalizationVersion { get; set; } = SharedIdentifiers.CanonicalizationVersion;

    /// <summary>
    /// Everything derived from the policy, grouped in one place (design §5.3, ratified by
    /// Danny's schema arbitration). A flat namespace is what invites a second copy of
    /// <c>policyVersion</c>; giving every policy-derived value one obvious home is what keeps
    /// the single-definition rule (epic §5.3.1) structurally true rather than merely observed.
    /// </summary>
    [JsonProperty("policy")]
    public ApprovalPolicySnapshot Policy { get; set; } = new();

    // ---- Façade over `policy.*` -------------------------------------------------------
    // Convenience for call sites only. These are NOT serialized: the wire shape is nested,
    // exactly once, per the ratified schema.

    [JsonIgnore]
    public string PolicyVersion
    {
        get => Policy.PolicyVersion;
        set => Policy.PolicyVersion = value;
    }

    [JsonIgnore]
    public string PolicyId
    {
        get => Policy.PolicyId;
        set => Policy.PolicyId = value;
    }

    [JsonIgnore]
    public Rung BaseRung
    {
        get => Policy.BaseRung;
        set => Policy.BaseRung = value;
    }

    [JsonIgnore]
    public Rung RequiredRung
    {
        get => Policy.RequiredRung;
        set => Policy.RequiredRung = value;
    }

    [JsonIgnore]
    public int RequiredSigners
    {
        get => Policy.RequiredSigners;
        set => Policy.RequiredSigners = value;
    }

    [JsonIgnore]
    public int MinSeniority
    {
        get => Policy.MinSeniority;
        set => Policy.MinSeniority = value;
    }

    [JsonIgnore]
    public List<FiredEscalator> FiredEscalators
    {
        get => Policy.FiredEscalators;
        set => Policy.FiredEscalators = value;
    }

    [JsonIgnore]
    public Dictionary<string, string> ResolvedThresholdSnapshot
    {
        get => Policy.ResolvedThresholdSnapshot;
        set => Policy.ResolvedThresholdSnapshot = value;
    }

    [JsonProperty("evidence")]
    public JObject Evidence { get; set; } = new();

    /// <summary>
    /// The facts the rung was evaluated against, frozen at proposal. Required so the §5.3.2
    /// execution-time re-evaluation is a comparison of POLICY versions, not of inputs — the
    /// only variable that may differ between the two evaluations is the ruleset.
    /// </summary>
    [JsonProperty("facts")]
    public JObject Facts { get; set; } = new();

    [JsonProperty("requesterRoles")]
    public List<string> RequesterRoles { get; set; } = [];

    [JsonProperty("requesterSeniority")]
    public int RequesterSeniority { get; set; }

    [JsonProperty("requesterSelfDealing")]
    public bool RequesterSelfDealing { get; set; }

    [JsonProperty("agentAssessment")]
    public JObject? AgentAssessment { get; set; }

    [JsonProperty("signatureSlots")]
    public List<SignatureSlot> SignatureSlots { get; set; } = [];

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    [JsonProperty("expiresAt")]
    public DateTime ExpiresAt { get; set; }

    /// <summary>Flat epoch-seconds copy of <see cref="ExpiresAt"/> so the sweep query is indexable.</summary>
    [JsonProperty("expiresAtEpoch")]
    public long ExpiresAtEpoch { get; set; }

    [JsonProperty("terminalAt")]
    public DateTime? TerminalAt { get; set; }

    /// <summary>
    /// MANDATORY once <see cref="Status"/> is <see cref="ApprovalStatus.Denied"/>; null otherwise.
    /// A <c>denied</c> record with no reason must be impossible to write (epic §5.1.1a) — the
    /// write guard rejects it before the upsert.
    /// </summary>
    [JsonProperty("terminalReason")]
    [JsonConverter(typeof(ThrowingTerminalReasonConverter))]
    public TerminalReason? TerminalReason { get; set; }

    /// <summary>Free text on <c>HUMAN_DENIED</c> only; structured detail otherwise.</summary>
    [JsonProperty("terminalDetail")]
    public string? TerminalDetail { get; set; }

    /// <summary>
    /// The replacement approval, when <c>PAYLOAD_SUPERSEDED</c> or <c>POLICY_RUNG_ESCALATED</c>
    /// produced one. Never <c>supersededBy</c>, never <c>supersededByProposalId</c> (epic §0.1).
    /// </summary>
    [JsonProperty("supersededByApprovalId")]
    public string? SupersededByApprovalId { get; set; }

    /// <summary>The approval this one replaced, if any. Lets the UI explain its own provenance.</summary>
    [JsonProperty("supersedesApprovalId")]
    public string? SupersedesApprovalId { get; set; }

    /// <summary>Denormalised for Q3 — the seniority the next unfilled slot demands. Null when complete.</summary>
    [JsonProperty("awaitingSeniority")]
    public int? AwaitingSeniority { get; set; }

    /// <summary>Denormalised for Q3 — the ordinal of the next unfilled slot. Null when complete.</summary>
    [JsonProperty("pendingSlotOrdinal")]
    public int? PendingSlotOrdinal { get; set; }

    [JsonProperty("batchId")]
    public string? BatchId { get; set; }

    [JsonProperty("execution")]
    public ExecutionRecord Execution { get; set; } = new();

    /// <summary>Set ONLY once terminal — the retention purge. Live approvals are immortal (design §5.4).</summary>
    [JsonProperty("ttl", NullValueHandling = NullValueHandling.Ignore)]
    public int? Ttl { get; set; }

    [JsonProperty("_etag", NullValueHandling = NullValueHandling.Ignore)]
    public string? ETag { get; set; }

    // ---- derived helpers (never persisted) ---------------------------------------------

    [JsonIgnore]
    public bool IsTerminal => Status is ApprovalStatus.Denied or ApprovalStatus.Executed;

    [JsonIgnore]
    public IReadOnlyList<string> SignerIds =>
        SignatureSlots.Where(s => s.SignedBy is not null).Select(s => s.SignedBy!).ToList();

    [JsonIgnore]
    public int SignaturesCollected => SignatureSlots.Count(s => s.SignedBy is not null);

    [JsonIgnore]
    public int DistinctSignerCount => SignerIds.Distinct(StringComparer.Ordinal).Count();
}

public class ApprovalTarget
{
    [JsonProperty("service")]
    public string Service { get; set; } = string.Empty;

    [JsonProperty("method")]
    public string Method { get; set; } = "POST";

    [JsonProperty("pathTemplate")]
    public string PathTemplate { get; set; } = string.Empty;

    /// <summary>
    /// The path template with <c>{placeholders}</c> substituted from the payload. The design's
    /// `pathParams` map is deliberately NOT carried alongside it: the two are the same fact in
    /// two representations, and the resolved path is the one the executor actually calls.
    /// </summary>
    [JsonProperty("resolvedPath")]
    public string ResolvedPath { get; set; } = string.Empty;
}

public class FiredEscalator
{
    [JsonProperty("key")]
    public string Key { get; set; } = string.Empty;

    [JsonProperty("raisedTo")]
    [JsonConverter(typeof(RungConverter))]
    public Rung RaisedTo { get; set; } = Rung.L1;

    [JsonProperty("scope")]
    public string Scope { get; set; } = "escalator";  // escalator | action_rule

    [JsonProperty("thresholdName")]
    public string? ThresholdName { get; set; }

    [JsonProperty("thresholdEnv")]
    public string? ThresholdEnv { get; set; }

    [JsonProperty("thresholdValue")]
    public string? ThresholdValue { get; set; }

    /// <summary>Rendered once, at evaluation time, and frozen. Surfaced verbatim to the signer.</summary>
    [JsonProperty("reason")]
    public string Reason { get; set; } = string.Empty;
}

public class SignatureSlot
{
    [JsonProperty("ordinal")]
    public int Ordinal { get; set; }

    [JsonProperty("minSeniority")]
    public int MinSeniority { get; set; } = 1;

    /// <summary>
    /// Separation of duties, made structural. There is no config value, policy rule, or
    /// escalator that can empty this list — the grammar has no verb for it (design §8.6.1).
    /// </summary>
    [JsonProperty("mustDifferFrom")]
    public List<string> MustDifferFrom { get; set; } = [];

    [JsonProperty("signedBy")]
    public string? SignedBy { get; set; }

    [JsonProperty("signedByUsername")]
    public string? SignedByUsername { get; set; }

    [JsonProperty("signedAt")]
    public DateTime? SignedAt { get; set; }

    [JsonProperty("signature")]
    public string? Signature { get; set; }

    [JsonProperty("signerTokenJti")]
    public string? SignerTokenJti { get; set; }

    [JsonProperty("nonce")]
    public string? Nonce { get; set; }

    // REMOVED: `rungSatisfied` and `boundPolicyVersion` were per-slot copies of
    // policy.requiredRung and policy.policyVersion. Under §5.3.2 a change to either VOIDS the
    // signatures and creates a replacement approval, so a filled slot's values are provably the
    // document's own — they could never diverge, only be stale. Both endpoints still appear on
    // the audit events, which are standalone records, sourced from the document's single copy.
    // (Same class as Danny's `execution.signedUnderPolicyVersion` removal, 2026-09-04.)

    [JsonProperty("comment")]
    public string? Comment { get; set; }
}

public class ExecutionRecord
{
    [JsonProperty("state")]
    [JsonConverter(typeof(ThrowingExecutionStateConverter))]
    public ExecutionState State { get; set; } = ExecutionState.NotAttempted;

    [JsonProperty("idempotencyKey")]
    public string? IdempotencyKey { get; set; }

    [JsonProperty("attempts")]
    public int Attempts { get; set; }

    [JsonProperty("startedAtEpoch")]
    public long? StartedAtEpoch { get; set; }

    [JsonProperty("downstreamStatus")]
    public int? DownstreamStatus { get; set; }

    [JsonProperty("downstreamRef")]
    public string? DownstreamRef { get; set; }

    [JsonProperty("lastError")]
    public string? LastError { get; set; }

    // REMOVED (Danny, 2026-09-04): `signedUnderPolicyVersion` was a second copy of
    // policy.policyVersion inside the same document. Under §5.3.2 the two are provably always
    // equal — a policy change VOIDS the signatures and creates a replacement approval — so the
    // field could only ever be wrong, never informative. It REMAINS on the audit events, which
    // are standalone flat records that must be readable without joining back to the document.
    // The rule is one copy per document, not one copy per system.

    /// <summary>
    /// The LIVE ruleset at execute time. A difference from the approval's own
    /// <c>policy.policyVersion</c> is an audit annotation ONLY and must never become a branch
    /// condition (design §6.4).
    /// </summary>
    [JsonProperty("evaluatedUnderPolicyVersion")]
    public string? EvaluatedUnderPolicyVersion { get; set; }
}

/// <summary>
/// The policy-derived half of an approval, frozen at evaluation time. Read back a year later
/// it shows the reasons AS THEY WERE EVALUATED, not re-rendered against today's config.
/// </summary>
public class ApprovalPolicySnapshot
{
    /// <summary>Human label for the policy. Stable across edits; never load-bearing.</summary>
    [JsonProperty("policyId")]
    public string PolicyId { get; set; } = string.Empty;

    /// <summary>
    /// The content hash of the RESOLVED policy this approval was evaluated under.
    /// <b>Single definition (epic §5.3.1)</b> — copied once at <c>proposed</c>, immutable
    /// thereafter, bound into the payload hash, and never re-derived at a use site.
    /// </summary>
    [JsonProperty("policyVersion")]
    public string PolicyVersion { get; set; } = string.Empty;

    [JsonProperty("baseRung")]
    [JsonConverter(typeof(RungConverter))]
    public Rung BaseRung { get; set; } = Rung.L1;

    [JsonProperty("requiredRung")]
    [JsonConverter(typeof(RungConverter))]
    public Rung RequiredRung { get; set; } = Rung.L1;

    [JsonProperty("requiredSigners")]
    public int RequiredSigners { get; set; } = 1;

    // REMOVED (Danny, 2026-09-04): `distinctIdentitiesRequired` always equalled
    // `requiredSigners`, and a count is the weaker control — a tally is satisfied by arithmetic
    // and a miscount passes silently, whereas `signatureSlots[].mustDifferFrom` names the
    // excluded identity and fails as a set-membership test against a specific subject.

    [JsonProperty("minSeniority")]
    public int MinSeniority { get; set; } = 1;

    /// <summary>Why the rung is what it is.</summary>
    [JsonProperty("firedEscalators")]
    public List<FiredEscalator> FiredEscalators { get; set; } = [];

    /// <summary>The resolved threshold values in force at evaluation time (design §3.5).</summary>
    [JsonProperty("resolvedThresholdSnapshot")]
    public Dictionary<string, string> ResolvedThresholdSnapshot { get; set; } = [];
}
