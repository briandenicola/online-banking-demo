using AuthorityService.LoanDecision.Contracts;
using AuthorityService.LoanDecision.Policy;
using System.Globalization;
using System.Text.RegularExpressions;

namespace AuthorityService.LoanDecision.Snapshots;

public sealed class LoanSnapshotValidationException : Exception
{
    public LoanSnapshotValidationException(string code, string message)
        : base($"{code}: {message}")
    {
        Code = code;
    }

    public string Code { get; }
}

public sealed class LoanSnapshotValidator
{
    public void ValidateRequest(LoanSnapshotRequestV1 request)
    {
        RequireSame(LoanContractVersions.SnapshotRequest, request.SchemaVersion, "snapshot request schema version");
        Require(request.Applicant.ApplicantId, "applicant.applicantId");
        Require(request.Application.ApplicationId, "application.applicationId");
        Require(request.Application.ApplicantId, "application.applicantId");
        Require(request.Action.ActionId, "action.actionId");
        Require(request.Action.ApplicationId, "action.applicationId");
        Require(request.Action.ApplicantId, "action.applicantId");
        Require(request.PolicyVersion, "policyVersion");
        RequireSame(request.Applicant.ApplicantId, request.Application.ApplicantId, "application applicant");
        RequireSame(request.Applicant.ApplicantId, request.Action.ApplicantId, "action applicant");
        RequireSame(request.Application.ApplicationId, request.Action.ApplicationId, "action application");
    }

    internal void ValidateStructure(LoanSnapshotInputV1 input)
    {
        Require(input.Applicant.ApplicantId, "applicant.applicantId");
        Require(input.Application.ApplicationId, "application.applicationId");
        Require(input.Application.ApplicantId, "application.applicantId");
        Require(input.Action.ActionId, "action.actionId");
        Require(input.Action.ApplicationId, "action.applicationId");
        Require(input.Action.ApplicantId, "action.applicantId");
        Require(input.PolicyVersion, "policyVersion");

        if (input.Action.ActionId != "loan.decision.record")
            Fail(LoanDecisionReasonCodes.BindingMismatch, "The action must be 'loan.decision.record'.");

        RequireSame(input.Applicant.ApplicantId, input.Application.ApplicantId, "application applicant");
        RequireSame(input.Applicant.ApplicantId, input.Action.ApplicantId, "action applicant");
        RequireSame(input.Application.ApplicationId, input.Action.ApplicationId, "action application");

        RequireUnique(input.Sources.Select(source => source.SourceId), "sourceId");
        RequireUnique(input.Documents.Select(document => document.DocumentId), "documentId");
        RequireUnique(input.Evidence.Select(evidence => evidence.EvidenceId), "evidenceId");
        RequireUnique(input.Facts.Select(fact => fact.Name), "fact name");

        if (input.Sources.Count == 0 || input.Evidence.Count == 0)
            Fail(LoanDecisionReasonCodes.EvidenceIncomplete, "At least one source and evidence item are required.");

        var sourceIds = input.Sources.Select(source => source.SourceId).ToHashSet(StringComparer.Ordinal);
        var documentIds = input.Documents.Select(document => document.DocumentId).ToHashSet(StringComparer.Ordinal);
        var evidenceIds = input.Evidence.Select(evidence => evidence.EvidenceId).ToHashSet(StringComparer.Ordinal);

        foreach (var source in input.Sources)
        {
            Require(source.RecordId, $"{source.SourceId}.recordId");
            RequireVersion(source.Version, source.Etag, source.SourceId);
            RequireTimestamp(source.RetrievedAt, $"{source.SourceId}.retrievedAt");
            RequireSame(input.Applicant.ApplicantId, source.ApplicantId, $"{source.SourceId} applicant");
            RequireSame(input.Application.ApplicationId, source.ApplicationId, $"{source.SourceId} application");
        }

        foreach (var document in input.Documents)
        {
            if (!sourceIds.Contains(document.SourceId))
                Fail(LoanDecisionReasonCodes.BindingMismatch, $"Document '{document.DocumentId}' has no bound source.");
            Require(document.SourceRecordId, $"{document.DocumentId}.sourceRecordId");
            RequireVersion(document.Version, document.Etag, document.DocumentId);
            RequireSame(input.Applicant.ApplicantId, document.ApplicantId, $"{document.DocumentId} applicant");
            RequireSame(input.Application.ApplicationId, document.ApplicationId, $"{document.DocumentId} application");
            var source = input.Sources.Single(item => item.SourceId == document.SourceId);
            RequireSame(source.RecordId, document.SourceRecordId, $"{document.DocumentId} source record");
            RequireRevision(source.Version, source.Etag, document.Version, document.Etag, document.DocumentId);
        }

        foreach (var evidence in input.Evidence)
        {
            if (!sourceIds.Contains(evidence.SourceId))
                Fail(LoanDecisionReasonCodes.BindingMismatch, $"Evidence '{evidence.EvidenceId}' has no bound source.");
            Require(evidence.SourceRecordId, $"{evidence.EvidenceId}.sourceRecordId");
            var source = input.Sources.Single(item => item.SourceId == evidence.SourceId);
            RequireSame(source.RecordId, evidence.SourceRecordId, $"{evidence.EvidenceId} source record");
            if (evidence.DocumentId is not null)
            {
                if (!documentIds.Contains(evidence.DocumentId))
                    Fail(LoanDecisionReasonCodes.BindingMismatch, $"Evidence '{evidence.EvidenceId}' has no bound document.");

                var document = input.Documents.Single(item => item.DocumentId == evidence.DocumentId);
                RequireSame(document.SourceId, evidence.SourceId, $"{evidence.EvidenceId} document source");
                RequireSame(document.SourceRecordId, evidence.SourceRecordId,
                    $"{evidence.EvidenceId} document source record");
                RequireRevision(
                    document.Version, document.Etag, evidence.Version, evidence.Etag, evidence.EvidenceId);
            }
            else
                RequireRevision(source.Version, source.Etag, evidence.Version, evidence.Etag, evidence.EvidenceId);
            RequireVersion(evidence.Version, evidence.Etag, evidence.EvidenceId);
            RequireTimestamp(evidence.RetrievedAt, $"{evidence.EvidenceId}.retrievedAt");
            RequireSame(input.Applicant.ApplicantId, evidence.ApplicantId, $"{evidence.EvidenceId} applicant");
            RequireSame(input.Application.ApplicationId, evidence.ApplicationId, $"{evidence.EvidenceId} application");
            RequireSame(input.Action.ActionId, evidence.ActionId, $"{evidence.EvidenceId} action");
        }

        var pagination = input.Completeness.Pagination;
        if (input.Completeness.Status != LoanCompletenessStatus.Complete ||
            input.Completeness.MissingEvidenceIds.Count > 0 ||
            pagination.Count == 0 ||
            pagination.Select(page => page.SourceId).Any(string.IsNullOrWhiteSpace) ||
            pagination.Select(page => page.SourceId)
                .GroupBy(id => id, StringComparer.Ordinal).Any(group => group.Count() > 1) ||
            !pagination.Select(page => page.SourceId).ToHashSet(StringComparer.Ordinal).SetEquals(sourceIds) ||
            pagination.Any(page =>
                !page.Terminated ||
                page.RepeatedToken ||
                page.PageCount <= 0 ||
                page.RecordCount < 0 ||
                page.RecordCount != input.Evidence.Count(item => item.SourceId == page.SourceId)))
        {
            Fail(LoanDecisionReasonCodes.EvidenceIncomplete, "Evidence completeness or pagination proof failed.");
        }

        if (input.Freshness.Count != input.Evidence.Count ||
            input.Freshness.Select(item => item.EvidenceId)
                .GroupBy(id => id, StringComparer.Ordinal).Any(group => group.Count() > 1) ||
            input.Freshness.Any(item => item.Status != LoanFreshnessStatus.Current) ||
            input.Freshness.Any(item => item.ObservedAt == default) ||
            input.Freshness.Select(item => item.EvidenceId).ToHashSet(StringComparer.Ordinal)
                .SetEquals(evidenceIds) is false)
        {
            Fail(LoanDecisionReasonCodes.EvidenceStale, "Every evidence item must have a CURRENT freshness result.");
        }

        RequireUnique(input.Contradictions.Select(item => item.Code), "contradiction code");
        if (input.Contradictions.Any(item =>
                item.Status is LoanContradictionStatus.Unknown or LoanContradictionStatus.Unresolved))
            Fail(LoanDecisionReasonCodes.EvidenceContradictory, "Unresolved material contradictions block a decision.");

        foreach (var contradiction in input.Contradictions)
        {
            if (contradiction.EvidenceIds.Count == 0 ||
                contradiction.EvidenceIds.Distinct(StringComparer.Ordinal).Count() != contradiction.EvidenceIds.Count ||
                contradiction.EvidenceIds.Any(id => !evidenceIds.Contains(id)))
            {
                Fail(LoanDecisionReasonCodes.BindingMismatch,
                    $"Contradiction '{contradiction.Code}' is not bound to unique known evidence.");
            }
        }

        foreach (var fact in input.Facts)
        {
            Require(fact.Name, "fact.name");
            Require(fact.Value, $"{fact.Name}.value");
            if (fact.Type == LoanFactType.Unknown)
                Fail(LoanDecisionReasonCodes.BindingMismatch, $"Fact '{fact.Name}' has an unknown type.");
            ValidateNormalizedValue(fact);
            if (fact.EvidenceIds.Count == 0 ||
                fact.EvidenceIds.Distinct(StringComparer.Ordinal).Count() != fact.EvidenceIds.Count ||
                fact.EvidenceIds.Any(id => !evidenceIds.Contains(id)))
                Fail(LoanDecisionReasonCodes.BindingMismatch, $"Fact '{fact.Name}' is not bound to known evidence.");
        }
    }

    public void ValidateForDecision(LoanDecisionSnapshotV1 snapshot, ResolvedLoanPolicy policy)
    {
        RequireSame(LoanContractVersions.Snapshot, snapshot.SchemaVersion, "snapshot schema version");
        ValidateStructure(new LoanSnapshotInputV1
        {
            Applicant = snapshot.Applicant,
            Application = snapshot.Application,
            Action = snapshot.Action,
            PolicyVersion = snapshot.PolicyVersion,
            Sources = snapshot.Sources,
            Documents = snapshot.Documents,
            Evidence = snapshot.Evidence,
            Completeness = snapshot.Completeness,
            Freshness = snapshot.Freshness,
            Contradictions = snapshot.Contradictions,
            Facts = snapshot.Facts
        });
        if (snapshot.PolicyVersion != policy.PolicyVersion)
            Fail(LoanDecisionReasonCodes.DigestMismatch, "Snapshot and policy versions differ.");

        var expectedAction = LoanDecisionDigests.Action(snapshot.Action);
        var expectedSnapshot = LoanDecisionDigests.Snapshot(snapshot);
        var expectedAuthority = LoanDecisionDigests.AuthoritativeSource(snapshot);
        var evidenceDigestsMatch =
            snapshot.EvidenceDigests.Count == snapshot.Evidence.Count &&
            snapshot.Evidence.All(evidence =>
                snapshot.EvidenceDigests.TryGetValue(evidence.EvidenceId, out var digest) &&
                digest == LoanDecisionDigests.Evidence(evidence));
        if (!evidenceDigestsMatch ||
            snapshot.Action.ActionDigest != expectedAction ||
            snapshot.AuthoritativeSourceDigest != expectedAuthority ||
            snapshot.SnapshotDigest != expectedSnapshot)
            Fail(LoanDecisionReasonCodes.DigestMismatch, "Snapshot or action digest does not match canonical content.");

        if (!policy.IsExecutable)
        {
            Fail(
                LoanDecisionReasonCodes.PolicyDefinitionUnresolved,
                "POL-001..POL-010 are provisional; no underwriting outcome is authorized.");
        }
    }

    public void ValidateOracleResult(LoanDecisionOracleResultV1 result)
    {
        RequireSame(LoanContractVersions.OracleResult, result.SchemaVersion, "oracle result schema version");
        if (result.Decision == LoanDecisionOutcome.Unknown)
            Fail(LoanDecisionReasonCodes.BindingMismatch, "Oracle decision is unknown.");
        Require(result.PolicyVersion, "oracleResult.policyVersion");
        Require(result.SnapshotDigest, "oracleResult.snapshotDigest");
        RequireUnique(result.ReasonCodes, "oracle reason code");

        foreach (var rule in result.RuleResults)
        {
            Require(rule.RuleId, "ruleResult.ruleId");
            Require(rule.ReasonCode, $"{rule.RuleId}.reasonCode");
            if (rule.Status == LoanRuleResultStatus.Unknown || rule.Outcome == LoanDecisionOutcome.Unknown)
                Fail(LoanDecisionReasonCodes.BindingMismatch,
                    $"Rule result '{rule.RuleId}' contains an unknown enum value.");
        }
    }

    public void ValidateReconciliation(LoanDecisionReconciliationV1 reconciliation)
    {
        RequireSame(
            LoanContractVersions.Reconciliation,
            reconciliation.SchemaVersion,
            "reconciliation schema version");
        if (reconciliation.Boundary == LoanReconciliationBoundary.Unknown ||
            reconciliation.Status == LoanReconciliationStatus.Unknown)
        {
            Fail(LoanDecisionReasonCodes.BindingMismatch,
                "Reconciliation boundary and status must be explicit.");
        }

        RequireUnique(reconciliation.MismatchCodes, "reconciliation mismatch code");
        if (reconciliation.PreviousBinding is not null)
            ValidateBinding(reconciliation.PreviousBinding, "previousBinding");
        if (reconciliation.CurrentBinding is not null)
            ValidateBinding(reconciliation.CurrentBinding, "currentBinding");
        if (reconciliation.Status == LoanReconciliationStatus.Match)
        {
            if (reconciliation.PreviousBinding is null || reconciliation.CurrentBinding is null ||
                reconciliation.MismatchCodes.Count != 0)
                Fail(LoanDecisionReasonCodes.BindingMismatch,
                    "MATCH requires complete prior/current bindings and no mismatch codes.");

            RequireBindingsEqual(reconciliation.PreviousBinding!, reconciliation.CurrentBinding!);
        }
        else if (reconciliation.MismatchCodes.Count == 0)
        {
            Fail(LoanDecisionReasonCodes.BindingMismatch,
                "MISMATCH and BLOCKED reconciliations require an explicit mismatch code.");
        }
    }

    private static void Require(string? value, string field)
    {
        if (string.IsNullOrWhiteSpace(value))
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{field} is required.");
    }

    private static void RequireVersion(string? version, string? etag, string subject)
    {
        if (string.IsNullOrWhiteSpace(version) && string.IsNullOrWhiteSpace(etag))
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{subject} requires a version or ETag.");
    }

    private static void RequireRevision(
        string? expectedVersion,
        string? expectedEtag,
        string? actualVersion,
        string? actualEtag,
        string subject)
    {
        if (!string.Equals(expectedVersion, actualVersion, StringComparison.Ordinal) ||
            !string.Equals(expectedEtag, actualEtag, StringComparison.Ordinal))
            Fail(LoanDecisionReasonCodes.BindingMismatch,
                $"{subject} is bound to the wrong source revision or ETag.");
    }

    private static void RequireTimestamp(DateTimeOffset value, string field)
    {
        if (value == default)
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{field} is required.");
    }

    private static void RequireSame(string expected, string actual, string subject)
    {
        if (!string.Equals(expected, actual, StringComparison.Ordinal))
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{subject} is bound to the wrong value.");
    }

    private static void RequireUnique(IEnumerable<string> values, string subject)
    {
        if (values.Any(string.IsNullOrWhiteSpace) ||
            values.GroupBy(value => value, StringComparer.Ordinal).Any(group => group.Count() > 1))
        {
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{subject} values must be non-empty and unique.");
        }
    }

    private static void ValidateNormalizedValue(LoanNormalizedFactV1 fact)
    {
        var valid = fact.Type switch
        {
            LoanFactType.String => !string.IsNullOrWhiteSpace(fact.Value),
            LoanFactType.Integer =>
                Regex.IsMatch(fact.Value, @"^-?(?:0|[1-9][0-9]*)$", RegexOptions.CultureInvariant) &&
                long.TryParse(fact.Value, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out _),
            LoanFactType.Decimal =>
                Regex.IsMatch(
                    fact.Value,
                    @"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
                    RegexOptions.CultureInvariant) &&
                decimal.TryParse(
                    fact.Value,
                    NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint,
                    CultureInfo.InvariantCulture,
                    out var number) &&
                fact.Value == number.ToString("G29", CultureInfo.InvariantCulture),
            LoanFactType.Boolean => fact.Value is "true" or "false",
            LoanFactType.Date => DateOnly.TryParseExact(
                fact.Value, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _),
            _ => false
        };

        if (!valid)
            Fail(LoanDecisionReasonCodes.BindingMismatch,
                $"Fact '{fact.Name}' value is not canonical for type {fact.Type}.");
    }

    private static void ValidateBinding(LoanDecisionBindingV1 binding, string field)
    {
        Require(binding.ApplicantId, $"{field}.applicantId");
        Require(binding.ApplicationId, $"{field}.applicationId");
        Require(binding.ActionId, $"{field}.actionId");
        Require(binding.PolicyVersion, $"{field}.policyVersion");
        if (binding.Decision == LoanDecisionOutcome.Unknown)
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{field}.decision must be explicit.");
        if (binding.ReasonCodes.Count == 0)
            Fail(LoanDecisionReasonCodes.BindingMismatch, $"{field}.reasonCodes must not be empty.");
        RequireUnique(binding.ReasonCodes, $"{field}.reasonCode");
        Require(binding.SnapshotDigest, $"{field}.snapshotDigest");
        Require(binding.PolicyResultDigest, $"{field}.policyResultDigest");
        Require(binding.ActionDigest, $"{field}.actionDigest");
        Require(binding.ApprovalBindingDigest, $"{field}.approvalBindingDigest");
        if (binding.ApprovalBindingDigest != LoanDecisionDigests.ApprovalBinding(binding))
            Fail(LoanDecisionReasonCodes.DigestMismatch, $"{field}.approvalBindingDigest is invalid.");
    }

    private static void RequireBindingsEqual(
        LoanDecisionBindingV1 previous,
        LoanDecisionBindingV1 current)
    {
        var fieldsMatch =
            previous.ApplicantId == current.ApplicantId &&
            previous.ApplicationId == current.ApplicationId &&
            previous.ActionId == current.ActionId &&
            previous.PolicyVersion == current.PolicyVersion &&
            previous.Decision == current.Decision &&
            previous.ReasonCodes.SequenceEqual(current.ReasonCodes, StringComparer.Ordinal) &&
            previous.SnapshotDigest == current.SnapshotDigest &&
            previous.PolicyResultDigest == current.PolicyResultDigest &&
            previous.ActionDigest == current.ActionDigest &&
            previous.ApprovalBindingDigest == current.ApprovalBindingDigest;
        if (!fieldsMatch)
            Fail(LoanDecisionReasonCodes.BindingMismatch,
                "MATCH prior/current identity, policy, result, reason, action, and approval bindings differ.");
    }

    private static void Fail(string code, string message) =>
        throw new LoanSnapshotValidationException(code, message);
}
