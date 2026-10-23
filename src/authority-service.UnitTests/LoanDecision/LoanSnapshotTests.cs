using AuthorityService.LoanDecision.Contracts;
using AuthorityService.LoanDecision.Policy;
using AuthorityService.LoanDecision.Snapshots;
using FluentAssertions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests.LoanDecision;

public sealed class LoanSnapshotTests
{
    [Fact]
    public void Unconfigured_production_source_fails_closed()
    {
        var reached = false;
        var source = new UnconfiguredLoanAuthoritativeSource();

        var act = () =>
        {
            reached = true;
            return new LoanSnapshotBuilder(source, new LoanSnapshotValidator())
                .BuildCanonical(LoanFixture.Request());
        };

        act.Should().Throw<LoanSnapshotValidationException>()
            .Where(error => error.Code == LoanDecisionReasonCodes.AuthoritativeSourceUnavailable);
        reached.Should().BeTrue("the fail-closed provider must actually be invoked");
    }

    [Fact]
    public void Builder_derives_complete_snapshot_from_deterministic_authoritative_enumeration()
    {
        var source = LoanFixture.Source(reversePages: true);
        var request = LoanFixture.Request();

        var snapshot = LoanFixture.Builder(source).BuildCanonical(request);

        source.CallCount.Should().Be(1, "the authoritative interface must be the retrieval path");
        snapshot.Sources.Select(item => item.SourceId).Should().Equal("application-source", "document-source");
        snapshot.Completeness.Status.Should().Be(LoanCompletenessStatus.Complete);
        snapshot.Completeness.Pagination.Should().OnlyContain(page => page.Terminated && !page.RepeatedToken);
        snapshot.EvidenceDigests.Should().ContainKey("evidence-1");
        snapshot.AuthoritativeSourceDigest.Should().StartWith("sha256:");
        snapshot.SnapshotDigest.Should().StartWith("sha256:");
    }

    [Theory]
    [InlineData("page-gap")]
    [InlineData("unterminated")]
    [InlineData("page-source-mismatch")]
    public void Hostile_authoritative_pagination_fails_closed(string mutation)
    {
        var pages = (List<LoanAuthoritativePageV1>)LoanFixture.Pages();
        var original = pages[0];
        pages[0] = new LoanAuthoritativePageV1
        {
            SourceId = mutation == "page-source-mismatch" ? "substitute-source" : original.SourceId,
            PageNumber = mutation == "page-gap" ? 2 : original.PageNumber,
            RequestToken = original.RequestToken,
            NextToken = mutation == "unterminated" ? "more" : original.NextToken,
            Source = original.Source,
            Records = original.Records
        };
        var applied = pages[0].SourceId != original.SourceId ||
                      pages[0].PageNumber != original.PageNumber ||
                      pages[0].NextToken != original.NextToken;
        applied.Should().BeTrue("Applied");
        var reached = false;

        var act = () =>
        {
            reached = true;
            return LoanFixture.Builder(new FakeLoanAuthoritativeSource(pages))
                .BuildCanonical(LoanFixture.Request());
        };

        act.Should().Throw<LoanSnapshotValidationException>("Killed");
        reached.Should().BeTrue("Reached");
    }

    [Theory]
    [InlineData("document-version")]
    [InlineData("document-etag")]
    [InlineData("document-record")]
    [InlineData("evidence-version")]
    [InlineData("evidence-etag")]
    [InlineData("evidence-record")]
    public void Initial_revision_or_record_substitution_is_rejected(string mutation)
    {
        var pages = LoanFixture.Pages();
        var record = pages.Single(page => page.SourceId == "document-source").Records.Single();
        var applied = LoanFixture.Substitute(pages, record, mutation);
        applied.Should().BeTrue("Applied: the requested hostile substitution must alter the fixture");
        var reached = false;

        var act = () =>
        {
            reached = true;
            return LoanFixture.Builder(new FakeLoanAuthoritativeSource(pages))
                .BuildCanonical(LoanFixture.Request());
        };

        act.Should().Throw<LoanSnapshotValidationException>()
            .Where(error => error.Code == LoanDecisionReasonCodes.BindingMismatch,
                "Killed: record identity and revision substitution must fail closed");
        reached.Should().BeTrue("Reached: validation must execute");
    }

    [Fact]
    public void Post_build_authoritative_revision_change_is_detected_before_policy_evaluation()
    {
        var initial = LoanFixture.Pages();
        var changed = LoanFixture.Pages();
        LoanFixture.AdvanceRevision(changed).Should().BeTrue("Applied");
        var source = new FakeLoanAuthoritativeSource(initial, changed);
        var reached = false;

        var act = () =>
        {
            reached = true;
            return LoanFixture.Builder(source).BuildForDecision(LoanFixture.Request(), LoanFixture.Policy());
        };

        act.Should().Throw<LoanSnapshotValidationException>()
            .Where(error => error.Code == LoanDecisionReasonCodes.AuthoritativeSourceChanged,
                "Killed: a post-build TOCTOU change must be detected before provisional policy blocking");
        reached.Should().BeTrue("Reached");
        source.CallCount.Should().Be(2, "the source must be re-enumerated at the decision boundary");
    }

    [Theory]
    [InlineData("extra", """{"applicantId":"a","unexpected":true}""")]
    [InlineData("integer-enum", """{"status":1,"missingEvidenceIds":[],"pagination":[]}""")]
    [InlineData("undefined-enum", """{"status":"NOT_A_STATUS","missingEvidenceIds":[],"pagination":[]}""")]
    [InlineData("missing-required", """{"missingEvidenceIds":[],"pagination":[]}""")]
    public void Strict_loan_JSON_rejects_unknown_missing_and_non_string_enum_values(
        string name,
        string json)
    {
        var applied = !string.IsNullOrWhiteSpace(json);
        applied.Should().BeTrue($"Applied: {name}");
        var reached = false;
        Action act = name == "extra"
            ? () => { reached = true; LoanContractSerialization.Deserialize<LoanApplicantBindingV1>(json); }
            : () => { reached = true; LoanContractSerialization.Deserialize<LoanCompletenessResultV1>(json); };

        act.Should().Throw<JsonSerializationException>($"Killed: {name}");
        reached.Should().BeTrue("Reached");
    }

    [Fact]
    public void Unknown_request_schema_version_fails_closed()
    {
        var json = JObject.Parse(LoanContractSerialization.Serialize(LoanFixture.Request()));
        json["schemaVersion"] = "loan-snapshot-request/v999";
        var request = LoanContractSerialization.Deserialize<LoanSnapshotRequestV1>(
            json.ToString(Formatting.None));
        request.SchemaVersion.Should().EndWith("/v999", "Applied");
        var reached = false;

        var act = () =>
        {
            reached = true;
            return LoanFixture.Builder(LoanFixture.Source()).BuildCanonical(request);
        };

        act.Should().Throw<LoanSnapshotValidationException>("Killed");
        reached.Should().BeTrue("Reached");
    }

    [Fact]
    public void Omitted_request_schema_version_cannot_default_to_v1()
    {
        var json = JObject.Parse(LoanContractSerialization.Serialize(LoanFixture.Request()));
        json.Remove("schemaVersion").Should().BeTrue("Applied");
        var reached = false;
        var act = () =>
        {
            reached = true;
            LoanContractSerialization.Deserialize<LoanSnapshotRequestV1>(json.ToString(Formatting.None));
        };
        act.Should().Throw<JsonSerializationException>("Killed");
        reached.Should().BeTrue("Reached");
    }

    [Fact]
    public void Digest_domains_are_distinct_and_material_changes_are_detected()
    {
        var snapshot = LoanFixture.Builder(LoanFixture.Source()).BuildCanonical(LoanFixture.Request());
        var result = new LoanDecisionOracleResultV1
        {
            Decision = LoanDecisionOutcome.Blocked,
            ReasonCodes = [LoanDecisionReasonCodes.PolicyDefinitionUnresolved],
            Conditions = [],
            HardStop = true,
            RuleResults = [],
            PolicyVersion = snapshot.PolicyVersion,
            SnapshotDigest = snapshot.SnapshotDigest!
        };
        result.ResultDigest = LoanDecisionDigests.PolicyResult(result);
        var binding = LoanFixture.Binding();
        var digests = new[]
        {
            snapshot.Action.ActionDigest!,
            snapshot.EvidenceDigests["evidence-1"],
            snapshot.AuthoritativeSourceDigest,
            snapshot.SnapshotDigest!,
            result.ResultDigest!,
            binding.ApprovalBindingDigest!
        };
        digests.Should().OnlyHaveUniqueItems("domain separation must be effective");

        var changed = LoanContractSerialization.Deserialize<LoanDecisionSnapshotV1>(
            LoanContractSerialization.Serialize(snapshot));
        changed.Action.Payload["requestedAmount"] = "25000.01";
        changed.Action.Payload["requestedAmount"]!.Value<string>().Should().Be("25000.01", "Applied");
        LoanDecisionDigests.Action(changed.Action).Should().NotBe(snapshot.Action.ActionDigest, "Killed");
        LoanDecisionDigests.Snapshot(changed).Should().NotBe(snapshot.SnapshotDigest, "Reached");
    }

    [Theory]
    [InlineData(LoanFactType.Integer, "01")]
    [InlineData(LoanFactType.Decimal, "1.00")]
    [InlineData(LoanFactType.Boolean, "True")]
    [InlineData(LoanFactType.Date, "09/17/2026")]
    [InlineData(LoanFactType.Unknown, "value")]
    public void Typed_facts_are_closed_and_canonical(LoanFactType type, string value)
    {
        var pages = LoanFixture.Pages();
        var record = pages.Single(page => page.SourceId == "document-source").Records.Single();
        record.Facts.Should().ContainSingle();
        var replacement = LoanFixture.CopyRecord(record, facts:
        [
            new LoanNormalizedFactV1
            {
                Name = "verifiedAnnualIncome", Type = type, Value = value,
                EvidenceIds = ["evidence-1"]
            }
        ]);
        LoanFixture.ReplaceRecord(pages, replacement);
        replacement.Facts.Single().Value.Should().Be(value, "Applied");

        var act = () => LoanFixture.Builder(new FakeLoanAuthoritativeSource(pages))
            .BuildCanonical(LoanFixture.Request());

        act.Should().Throw<LoanSnapshotValidationException>()
            .Where(error => error.Code == LoanDecisionReasonCodes.BindingMismatch, "Killed");
    }

    [Fact]
    public void Nested_evidence_order_is_canonical_and_membership_is_material()
    {
        var firstPages = LoanFixture.Pages(twoEvidence: true);
        var secondPages = LoanFixture.Pages(twoEvidence: true, reverseNestedEvidenceIds: true);
        var first = LoanFixture.Builder(new FakeLoanAuthoritativeSource(firstPages))
            .BuildCanonical(LoanFixture.Request());
        var second = LoanFixture.Builder(new FakeLoanAuthoritativeSource(secondPages))
            .BuildCanonical(LoanFixture.Request());
        first.Facts.Single().EvidenceIds.Should().NotEqual(
            secondPages.Single(page => page.SourceId == "document-source")
                .Records.Last().Facts.Single().EvidenceIds, "Applied");
        first.SnapshotDigest.Should().Be(second.SnapshotDigest, "Reached and canonicalized");

        var materialPages = LoanFixture.Pages(twoEvidence: true);
        var materialRecord = materialPages.Single(page => page.SourceId == "document-source").Records.Last();
        LoanFixture.ReplaceRecord(materialPages, LoanFixture.CopyRecord(materialRecord, facts:
        [
            new LoanNormalizedFactV1
            {
                Name = "verifiedAnnualIncome", Type = LoanFactType.Decimal, Value = "100000",
                EvidenceIds = ["evidence-2"]
            }
        ]));
        var material = LoanFixture.Builder(new FakeLoanAuthoritativeSource(materialPages))
            .BuildCanonical(LoanFixture.Request());
        material.SnapshotDigest.Should().NotBe(first.SnapshotDigest,
            "Killed: a material evidence-membership change must alter the digest");
    }

    [Fact]
    public void Provisional_policy_remains_non_executable()
    {
        var source = LoanFixture.Source();
        var act = () => LoanFixture.Builder(source)
            .BuildForDecision(LoanFixture.Request(), LoanFixture.Policy());

        act.Should().Throw<LoanSnapshotValidationException>()
            .Where(error => error.Code == LoanDecisionReasonCodes.PolicyDefinitionUnresolved);
        source.CallCount.Should().Be(2, "the authoritative TOCTOU guard must be reached first");
    }

    [Fact]
    public void Reconciliation_match_requires_every_bound_value_to_match()
    {
        var previous = LoanFixture.Binding();
        var current = LoanFixture.Binding();
        var validator = new LoanSnapshotValidator();
        var valid = new LoanDecisionReconciliationV1
        {
            Boundary = LoanReconciliationBoundary.Approval,
            Status = LoanReconciliationStatus.Match,
            PreviousBinding = previous,
            CurrentBinding = current,
            MismatchCodes = []
        };
        validator.ValidateReconciliation(valid);

        var mismatched = LoanFixture.Binding(policyVersion: "lpv1:changed");
        var hostile = new LoanDecisionReconciliationV1
        {
            Boundary = LoanReconciliationBoundary.Approval,
            Status = LoanReconciliationStatus.Match,
            PreviousBinding = previous,
            CurrentBinding = mismatched,
            MismatchCodes = []
        };
        mismatched.PolicyVersion.Should().NotBe(previous.PolicyVersion, "Applied");
        var act = () => validator.ValidateReconciliation(hostile);
        act.Should().Throw<LoanSnapshotValidationException>("Killed");
    }

    [Theory]
    [InlineData("applicantId")]
    [InlineData("applicationId")]
    [InlineData("actionId")]
    [InlineData("policyVersion")]
    [InlineData("decision")]
    [InlineData("reasonCodes")]
    [InlineData("snapshotDigest")]
    [InlineData("policyResultDigest")]
    [InlineData("actionDigest")]
    public void Match_rejects_each_changed_identity_policy_result_reason_or_digest(string field)
    {
        var previous = LoanFixture.Binding();
        var json = JObject.Parse(LoanContractSerialization.Serialize(previous));
        json[field] = field switch
        {
            "decision" => "DECLINE",
            "reasonCodes" => new JArray("CHANGED_REASON"),
            _ => json[field] + "-changed"
        };
        var current = LoanContractSerialization.Deserialize<LoanDecisionBindingV1>(
            json.ToString(Formatting.None));
        current.ApprovalBindingDigest = LoanDecisionDigests.ApprovalBinding(current);
        JToken.DeepEquals(
            JObject.Parse(LoanContractSerialization.Serialize(previous))[field],
            JObject.Parse(LoanContractSerialization.Serialize(current))[field])
            .Should().BeFalse("Applied");
        var reconciliation = new LoanDecisionReconciliationV1
        {
            Boundary = LoanReconciliationBoundary.Approval,
            Status = LoanReconciliationStatus.Match,
            PreviousBinding = previous,
            CurrentBinding = current,
            MismatchCodes = []
        };
        var reached = false;
        var act = () =>
        {
            reached = true;
            new LoanSnapshotValidator().ValidateReconciliation(reconciliation);
        };
        act.Should().Throw<LoanSnapshotValidationException>("Killed");
        reached.Should().BeTrue("Reached");
    }

    [Theory]
    [InlineData(LoanReconciliationStatus.Match, false, false)]
    [InlineData(LoanReconciliationStatus.Mismatch, true, false)]
    [InlineData(LoanReconciliationStatus.Blocked, true, false)]
    public void Reconciliation_status_semantics_fail_closed(
        LoanReconciliationStatus status,
        bool includeBindings,
        bool includeCode)
    {
        var reconciliation = new LoanDecisionReconciliationV1
        {
            Boundary = LoanReconciliationBoundary.Execution,
            Status = status,
            PreviousBinding = includeBindings ? LoanFixture.Binding() : null,
            CurrentBinding = includeBindings ? LoanFixture.Binding() : null,
            MismatchCodes = includeCode ? ["EXPECTED_MISMATCH"] : []
        };
        var reached = false;
        var act = () =>
        {
            reached = true;
            new LoanSnapshotValidator().ValidateReconciliation(reconciliation);
        };
        act.Should().Throw<LoanSnapshotValidationException>("Killed");
        reached.Should().BeTrue("Reached");
    }
}

internal sealed class FakeLoanAuthoritativeSource(params IReadOnlyList<LoanAuthoritativePageV1>[] results)
    : ILoanAuthoritativeSource
{
    public int CallCount { get; private set; }

    public IReadOnlyList<LoanAuthoritativePageV1> Enumerate(LoanAuthoritativeQueryV1 query)
    {
        var index = Math.Min(CallCount, results.Length - 1);
        CallCount++;
        return results[index];
    }
}

internal static class LoanFixture
{
    private static readonly DateTimeOffset RetrievedAt =
        new(2026, 9, 17, 20, 0, 0, TimeSpan.Zero);

    public static LoanSnapshotBuilder Builder(ILoanAuthoritativeSource source) =>
        new(source, new LoanSnapshotValidator());

    public static FakeLoanAuthoritativeSource Source(bool reversePages = false) =>
        new(Pages(reversePages));

    public static LoanSnapshotRequestV1 Request() => new()
    {
        Applicant = new LoanApplicantBindingV1 { ApplicantId = "applicant-1" },
        Application = new LoanApplicationBindingV1
        {
            ApplicationId = "application-1", ApplicantId = "applicant-1"
        },
        Action = new LoanActionBindingV1
        {
            ActionId = "loan.decision.record",
            ApplicationId = "application-1",
            ApplicantId = "applicant-1",
            Payload = JObject.Parse("""{"requestedAmount":"25000.00"}""")
        },
        PolicyVersion = Policy().PolicyVersion
    };

    public static IReadOnlyList<LoanAuthoritativePageV1> Pages(
        bool reversePages = false,
        bool twoEvidence = false,
        bool reverseNestedEvidenceIds = false)
    {
        var source = new LoanSourceBindingV1
        {
            SourceId = "document-source", RecordId = "record-1", Version = "v1", Etag = "etag-1",
            RetrievedAt = RetrievedAt, ApplicantId = "applicant-1", ApplicationId = "application-1"
        };
        var first = Record("evidence-1", source, includeFact: !twoEvidence);
        var documentRecords = new List<LoanAuthoritativeRecordV1> { first };
        if (twoEvidence)
        {
            documentRecords.Add(Record("evidence-2", source, includeFact: true,
                evidenceIds: reverseNestedEvidenceIds
                    ? ["evidence-2", "evidence-1"]
                    : ["evidence-1", "evidence-2"]));
        }

        var pages = new List<LoanAuthoritativePageV1>
        {
            new()
            {
                SourceId = source.SourceId, PageNumber = 1, RequestToken = null, NextToken = null,
                Source = source, Records = documentRecords
            },
            new()
            {
                SourceId = "application-source", PageNumber = 1, RequestToken = null, NextToken = null,
                Source = new LoanSourceBindingV1
                {
                    SourceId = "application-source", RecordId = "application-1", Version = "v3",
                    Etag = null, RetrievedAt = RetrievedAt, ApplicantId = "applicant-1",
                    ApplicationId = "application-1"
                },
                Records = []
            }
        };
        if (reversePages) pages.Reverse();
        return pages;
    }

    private static LoanAuthoritativeRecordV1 Record(
        string evidenceId,
        LoanSourceBindingV1 source,
        bool includeFact,
        IReadOnlyList<string>? evidenceIds = null)
    {
        var facts = includeFact
            ? new[]
            {
                new LoanNormalizedFactV1
                {
                    Name = "verifiedAnnualIncome", Type = LoanFactType.Decimal, Value = "100000",
                    EvidenceIds = evidenceIds ?? [evidenceId]
                }
            }
            : [];
        return new LoanAuthoritativeRecordV1
        {
            Document = new LoanDocumentBindingV1
            {
                DocumentId = "doc-1", SourceId = source.SourceId, SourceRecordId = source.RecordId,
                Version = source.Version, Etag = source.Etag, ApplicantId = source.ApplicantId,
                ApplicationId = source.ApplicationId
            },
            Evidence = new LoanEvidenceItemV1
            {
                EvidenceId = evidenceId, SourceId = source.SourceId, SourceRecordId = source.RecordId,
                DocumentId = "doc-1", ApplicantId = source.ApplicantId,
                ApplicationId = source.ApplicationId, ActionId = "loan.decision.record",
                Version = source.Version, Etag = source.Etag, RetrievedAt = RetrievedAt,
                Payload = JObject.Parse("""{"verified":true}""")
            },
            Freshness = new LoanFreshnessResultV1
            {
                EvidenceId = evidenceId, Status = LoanFreshnessStatus.Current, ObservedAt = RetrievedAt
            },
            Facts = facts
        };
    }

    public static bool Substitute(
        IReadOnlyList<LoanAuthoritativePageV1> pages,
        LoanAuthoritativeRecordV1 record,
        string mutation)
    {
        var document = record.Document!;
        var evidence = record.Evidence!;
        var changedDocument = new LoanDocumentBindingV1
        {
            DocumentId = document.DocumentId, SourceId = document.SourceId,
            SourceRecordId = mutation == "document-record" ? "substitute-record" : document.SourceRecordId,
            Version = mutation == "document-version" ? "v2" : document.Version,
            Etag = mutation == "document-etag" ? "etag-2" : document.Etag,
            ApplicantId = document.ApplicantId, ApplicationId = document.ApplicationId
        };
        var changedEvidence = new LoanEvidenceItemV1
        {
            EvidenceId = evidence.EvidenceId, SourceId = evidence.SourceId,
            SourceRecordId = mutation == "evidence-record" ? "substitute-record" : evidence.SourceRecordId,
            DocumentId = evidence.DocumentId, ApplicantId = evidence.ApplicantId,
            ApplicationId = evidence.ApplicationId, ActionId = evidence.ActionId,
            Version = mutation == "evidence-version" ? "v2" : evidence.Version,
            Etag = mutation == "evidence-etag" ? "etag-2" : evidence.Etag,
            RetrievedAt = evidence.RetrievedAt, Payload = evidence.Payload
        };
        ReplaceRecord(pages, CopyRecord(record, changedDocument, changedEvidence), record);
        return mutation switch
        {
            "document-record" => changedDocument.SourceRecordId != document.SourceRecordId,
            "document-version" => changedDocument.Version != document.Version,
            "document-etag" => changedDocument.Etag != document.Etag,
            "evidence-record" => changedEvidence.SourceRecordId != evidence.SourceRecordId,
            "evidence-version" => changedEvidence.Version != evidence.Version,
            "evidence-etag" => changedEvidence.Etag != evidence.Etag,
            _ => false
        };
    }

    public static bool AdvanceRevision(IReadOnlyList<LoanAuthoritativePageV1> pages)
    {
        var list = (List<LoanAuthoritativePageV1>)pages;
        var index = list.FindIndex(page => page.SourceId == "document-source");
        var page = list[index];
        var oldSource = page.Source;
        var source = new LoanSourceBindingV1
        {
            SourceId = oldSource.SourceId, RecordId = oldSource.RecordId, Version = "v2", Etag = "etag-2",
            RetrievedAt = oldSource.RetrievedAt, ApplicantId = oldSource.ApplicantId,
            ApplicationId = oldSource.ApplicationId
        };
        var records = page.Records.Select(record =>
        {
            var document = record.Document!;
            var evidence = record.Evidence!;
            return CopyRecord(
                record,
                new LoanDocumentBindingV1
                {
                    DocumentId = document.DocumentId, SourceId = document.SourceId,
                    SourceRecordId = document.SourceRecordId, Version = source.Version, Etag = source.Etag,
                    ApplicantId = document.ApplicantId, ApplicationId = document.ApplicationId
                },
                new LoanEvidenceItemV1
                {
                    EvidenceId = evidence.EvidenceId, SourceId = evidence.SourceId,
                    SourceRecordId = evidence.SourceRecordId, DocumentId = evidence.DocumentId,
                    ApplicantId = evidence.ApplicantId, ApplicationId = evidence.ApplicationId,
                    ActionId = evidence.ActionId, Version = source.Version, Etag = source.Etag,
                    RetrievedAt = evidence.RetrievedAt, Payload = evidence.Payload
                });
        }).ToList();
        list[index] = new LoanAuthoritativePageV1
        {
            SourceId = page.SourceId, PageNumber = page.PageNumber,
            RequestToken = page.RequestToken, NextToken = page.NextToken,
            Source = source, Records = records
        };
        return oldSource.Version != source.Version && oldSource.Etag != source.Etag;
    }

    public static void ReplaceRecord(
        IReadOnlyList<LoanAuthoritativePageV1> pages,
        LoanAuthoritativeRecordV1 replacement,
        LoanAuthoritativeRecordV1? original = null)
    {
        var page = pages.Single(item => item.SourceId == "document-source");
        var records = (List<LoanAuthoritativeRecordV1>)page.Records;
        var index = original is null ? records.Count - 1 : records.IndexOf(original);
        if (index < 0) index = records.Count - 1;
        records[index] = replacement;
    }

    public static LoanAuthoritativeRecordV1 CopyRecord(
        LoanAuthoritativeRecordV1 record,
        LoanDocumentBindingV1? document = null,
        LoanEvidenceItemV1? evidence = null,
        IReadOnlyList<LoanNormalizedFactV1>? facts = null) =>
        new()
        {
            Document = document ?? record.Document,
            Evidence = evidence ?? record.Evidence,
            Freshness = record.Freshness,
            Contradictions = record.Contradictions,
            Facts = facts ?? record.Facts
        };

    public static ResolvedLoanPolicy Policy()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var path = Path.Combine(directory.FullName, "config", "loan-underwriting-policy.yaml");
            if (File.Exists(path)) return new LoanPolicyLoader().LoadFromFile(path);
            directory = directory.Parent;
        }
        throw new FileNotFoundException("Could not locate loan-underwriting-policy.yaml.");
    }

    public static LoanDecisionBindingV1 Binding(string policyVersion = "lpv1:test")
    {
        var binding = new LoanDecisionBindingV1
        {
            ApplicantId = "applicant-1",
            ApplicationId = "application-1",
            ActionId = "loan.decision.record",
            PolicyVersion = policyVersion,
            Decision = LoanDecisionOutcome.Blocked,
            ReasonCodes = [LoanDecisionReasonCodes.PolicyDefinitionUnresolved],
            SnapshotDigest = "sha256:snapshot",
            PolicyResultDigest = "sha256:result",
            ActionDigest = "sha256:action"
        };
        binding.ApprovalBindingDigest = LoanDecisionDigests.ApprovalBinding(binding);
        return binding;
    }
}
