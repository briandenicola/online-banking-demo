using System.Runtime.Serialization;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;
using Newtonsoft.Json.Linq;

namespace AuthorityService.LoanDecision.Contracts;

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanCompletenessStatus
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "COMPLETE")] Complete,
    [EnumMember(Value = "INCOMPLETE")] Incomplete,
    [EnumMember(Value = "AMBIGUOUS")] Ambiguous
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanFreshnessStatus
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "CURRENT")] Current,
    [EnumMember(Value = "STALE")] Stale
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanContradictionStatus
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "NONE")] None,
    [EnumMember(Value = "RESOLVED")] Resolved,
    [EnumMember(Value = "UNRESOLVED")] Unresolved
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanFactType
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "STRING")] String,
    [EnumMember(Value = "INTEGER")] Integer,
    [EnumMember(Value = "DECIMAL")] Decimal,
    [EnumMember(Value = "BOOLEAN")] Boolean,
    [EnumMember(Value = "DATE")] Date
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanDecisionOutcome
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "BLOCKED")] Blocked,
    [EnumMember(Value = "APPROVE")] Approve,
    [EnumMember(Value = "CONDITIONAL")] Conditional,
    [EnumMember(Value = "DECLINE")] Decline
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanRuleResultStatus
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "NOT_EVALUATED")] NotEvaluated,
    [EnumMember(Value = "MATCHED")] Matched,
    [EnumMember(Value = "NOT_MATCHED")] NotMatched,
    [EnumMember(Value = "BLOCKED")] Blocked
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanReconciliationBoundary
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "PROPOSAL")] Proposal,
    [EnumMember(Value = "APPROVAL")] Approval,
    [EnumMember(Value = "EXECUTION")] Execution
}

[JsonConverter(typeof(ClosedStringEnumConverter))]
public enum LoanReconciliationStatus
{
    [EnumMember(Value = "UNKNOWN")] Unknown,
    [EnumMember(Value = "MATCH")] Match,
    [EnumMember(Value = "MISMATCH")] Mismatch,
    [EnumMember(Value = "BLOCKED")] Blocked
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanApplicantBindingV1
{
    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanApplicationBindingV1
{
    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }

    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanActionBindingV1
{
    [JsonProperty("actionId")]
    public required string ActionId { get; init; }

    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }

    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }

    [JsonProperty("payload")]
    public required JObject Payload { get; init; }

    [JsonProperty("actionDigest", Required = Required.AllowNull)]
    public string? ActionDigest { get; set; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanSourceBindingV1
{
    [JsonProperty("sourceId")]
    public required string SourceId { get; init; }

    [JsonProperty("recordId")]
    public required string RecordId { get; init; }

    [JsonProperty("version", Required = Required.AllowNull)]
    public string? Version { get; init; }

    [JsonProperty("etag", Required = Required.AllowNull)]
    public string? Etag { get; init; }

    [JsonProperty("retrievedAt")]
    public required DateTimeOffset RetrievedAt { get; init; }

    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }

    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanDocumentBindingV1
{
    [JsonProperty("documentId")]
    public required string DocumentId { get; init; }

    [JsonProperty("sourceId")]
    public required string SourceId { get; init; }

    [JsonProperty("sourceRecordId")]
    public required string SourceRecordId { get; init; }

    [JsonProperty("version", Required = Required.AllowNull)]
    public string? Version { get; init; }

    [JsonProperty("etag", Required = Required.AllowNull)]
    public string? Etag { get; init; }

    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }

    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanEvidenceItemV1
{
    [JsonProperty("evidenceId")]
    public required string EvidenceId { get; init; }

    [JsonProperty("sourceId")]
    public required string SourceId { get; init; }

    [JsonProperty("sourceRecordId")]
    public required string SourceRecordId { get; init; }

    [JsonProperty("documentId", Required = Required.AllowNull)]
    public string? DocumentId { get; init; }

    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }

    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }

    [JsonProperty("actionId")]
    public required string ActionId { get; init; }

    [JsonProperty("version", Required = Required.AllowNull)]
    public string? Version { get; init; }

    [JsonProperty("etag", Required = Required.AllowNull)]
    public string? Etag { get; init; }

    [JsonProperty("retrievedAt")]
    public required DateTimeOffset RetrievedAt { get; init; }

    [JsonProperty("payload")]
    public required JObject Payload { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanPaginationProofV1
{
    [JsonProperty("sourceId")]
    public required string SourceId { get; init; }

    [JsonProperty("pageCount")]
    public required int PageCount { get; init; }

    [JsonProperty("recordCount")]
    public required int RecordCount { get; init; }

    [JsonProperty("terminated")]
    public required bool Terminated { get; init; }

    [JsonProperty("repeatedToken")]
    public required bool RepeatedToken { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanCompletenessResultV1
{
    [JsonProperty("status")]
    public required LoanCompletenessStatus Status { get; init; }

    [JsonProperty("missingEvidenceIds")]
    public IReadOnlyList<string> MissingEvidenceIds { get; init; } = [];

    [JsonProperty("pagination")]
    public IReadOnlyList<LoanPaginationProofV1> Pagination { get; init; } = [];
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanFreshnessResultV1
{
    [JsonProperty("evidenceId")]
    public required string EvidenceId { get; init; }

    [JsonProperty("status")]
    public required LoanFreshnessStatus Status { get; init; }

    [JsonProperty("observedAt")]
    public required DateTimeOffset ObservedAt { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanContradictionResultV1
{
    [JsonProperty("code")]
    public required string Code { get; init; }

    [JsonProperty("status")]
    public required LoanContradictionStatus Status { get; init; }

    [JsonProperty("evidenceIds")]
    public IReadOnlyList<string> EvidenceIds { get; init; } = [];
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanNormalizedFactV1
{
    [JsonProperty("name")]
    public required string Name { get; init; }

    [JsonProperty("type")]
    public required LoanFactType Type { get; init; }

    [JsonProperty("value")]
    public required string Value { get; init; }

    [JsonProperty("evidenceIds")]
    public IReadOnlyList<string> EvidenceIds { get; init; } = [];
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanSnapshotRequestV1
{
    [JsonProperty("schemaVersion")]
    public string SchemaVersion { get; init; } = LoanContractVersions.SnapshotRequest;

    [JsonProperty("applicant")]
    public required LoanApplicantBindingV1 Applicant { get; init; }

    [JsonProperty("application")]
    public required LoanApplicationBindingV1 Application { get; init; }

    [JsonProperty("action")]
    public required LoanActionBindingV1 Action { get; init; }

    [JsonProperty("policyVersion")]
    public required string PolicyVersion { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
internal sealed class LoanSnapshotInputV1
{
    [JsonProperty("applicant")]
    public required LoanApplicantBindingV1 Applicant { get; init; }

    [JsonProperty("application")]
    public required LoanApplicationBindingV1 Application { get; init; }

    [JsonProperty("action")]
    public required LoanActionBindingV1 Action { get; init; }

    [JsonProperty("policyVersion")]
    public required string PolicyVersion { get; init; }

    [JsonProperty("sources")]
    public IReadOnlyList<LoanSourceBindingV1> Sources { get; init; } = [];

    [JsonProperty("documents")]
    public IReadOnlyList<LoanDocumentBindingV1> Documents { get; init; } = [];

    [JsonProperty("evidence")]
    public IReadOnlyList<LoanEvidenceItemV1> Evidence { get; init; } = [];

    [JsonProperty("completeness")]
    public required LoanCompletenessResultV1 Completeness { get; init; }

    [JsonProperty("freshness")]
    public IReadOnlyList<LoanFreshnessResultV1> Freshness { get; init; } = [];

    [JsonProperty("contradictions")]
    public IReadOnlyList<LoanContradictionResultV1> Contradictions { get; init; } = [];

    [JsonProperty("facts")]
    public IReadOnlyList<LoanNormalizedFactV1> Facts { get; init; } = [];
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanDecisionSnapshotV1
{
    [JsonProperty("schemaVersion")]
    public string SchemaVersion { get; init; } = LoanContractVersions.Snapshot;

    [JsonProperty("applicant")]
    public required LoanApplicantBindingV1 Applicant { get; init; }

    [JsonProperty("application")]
    public required LoanApplicationBindingV1 Application { get; init; }

    [JsonProperty("action")]
    public required LoanActionBindingV1 Action { get; init; }

    [JsonProperty("policyVersion")]
    public required string PolicyVersion { get; init; }

    [JsonProperty("sources")]
    public required IReadOnlyList<LoanSourceBindingV1> Sources { get; init; }

    [JsonProperty("documents")]
    public required IReadOnlyList<LoanDocumentBindingV1> Documents { get; init; }

    [JsonProperty("evidence")]
    public required IReadOnlyList<LoanEvidenceItemV1> Evidence { get; init; }

    [JsonProperty("completeness")]
    public required LoanCompletenessResultV1 Completeness { get; init; }

    [JsonProperty("freshness")]
    public required IReadOnlyList<LoanFreshnessResultV1> Freshness { get; init; }

    [JsonProperty("contradictions")]
    public required IReadOnlyList<LoanContradictionResultV1> Contradictions { get; init; }

    [JsonProperty("facts")]
    public required IReadOnlyList<LoanNormalizedFactV1> Facts { get; init; }

    [JsonProperty("evidenceDigests")]
    public required IReadOnlyDictionary<string, string> EvidenceDigests { get; init; }

    [JsonProperty("authoritativeSourceDigest")]
    public required string AuthoritativeSourceDigest { get; init; }

    [JsonProperty("snapshotDigest", Required = Required.AllowNull)]
    public string? SnapshotDigest { get; set; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanRuleResultV1
{
    [JsonProperty("ruleId")]
    public required string RuleId { get; init; }

    [JsonProperty("status")]
    public required LoanRuleResultStatus Status { get; init; }

    [JsonProperty("outcome")]
    public required LoanDecisionOutcome Outcome { get; init; }

    [JsonProperty("reasonCode")]
    public required string ReasonCode { get; init; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanDecisionOracleResultV1
{
    [JsonProperty("schemaVersion")]
    public string SchemaVersion { get; init; } = LoanContractVersions.OracleResult;

    [JsonProperty("decision")]
    public required LoanDecisionOutcome Decision { get; init; }

    [JsonProperty("reasonCodes")]
    public IReadOnlyList<string> ReasonCodes { get; init; } = [];

    [JsonProperty("conditions")]
    public IReadOnlyList<string> Conditions { get; init; } = [];

    [JsonProperty("hardStop")]
    public required bool HardStop { get; init; }

    [JsonProperty("ruleResults")]
    public IReadOnlyList<LoanRuleResultV1> RuleResults { get; init; } = [];

    [JsonProperty("policyVersion")]
    public required string PolicyVersion { get; init; }

    [JsonProperty("snapshotDigest")]
    public required string SnapshotDigest { get; init; }

    [JsonProperty("resultDigest", Required = Required.AllowNull)]
    public string? ResultDigest { get; set; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanDecisionBindingV1
{
    [JsonProperty("applicantId")]
    public required string ApplicantId { get; init; }

    [JsonProperty("applicationId")]
    public required string ApplicationId { get; init; }

    [JsonProperty("actionId")]
    public required string ActionId { get; init; }

    [JsonProperty("policyVersion")]
    public required string PolicyVersion { get; init; }

    [JsonProperty("decision")]
    public required LoanDecisionOutcome Decision { get; init; }

    [JsonProperty("reasonCodes")]
    public required IReadOnlyList<string> ReasonCodes { get; init; }

    [JsonProperty("snapshotDigest")]
    public required string SnapshotDigest { get; init; }

    [JsonProperty("policyResultDigest")]
    public required string PolicyResultDigest { get; init; }

    [JsonProperty("actionDigest")]
    public required string ActionDigest { get; init; }

    [JsonProperty("approvalBindingDigest", Required = Required.AllowNull)]
    public string? ApprovalBindingDigest { get; set; }
}

[JsonObject(ItemRequired = Required.Always)]
public sealed class LoanDecisionReconciliationV1
{
    [JsonProperty("schemaVersion")]
    public string SchemaVersion { get; init; } = LoanContractVersions.Reconciliation;

    [JsonProperty("boundary")]
    public required LoanReconciliationBoundary Boundary { get; init; }

    [JsonProperty("status")]
    public required LoanReconciliationStatus Status { get; init; }

    [JsonProperty("previousBinding", Required = Required.AllowNull)]
    public LoanDecisionBindingV1? PreviousBinding { get; init; }

    [JsonProperty("currentBinding", Required = Required.AllowNull)]
    public LoanDecisionBindingV1? CurrentBinding { get; init; }

    [JsonProperty("mismatchCodes")]
    public IReadOnlyList<string> MismatchCodes { get; init; } = [];
}

public static class LoanContractVersions
{
    public const string SnapshotRequest = "loan-snapshot-request/v1";
    public const string Snapshot = "loan-decision-snapshot/v1";
    public const string OracleResult = "loan-decision-result/v1";
    public const string Reconciliation = "loan-decision-reconciliation/v1";
}
