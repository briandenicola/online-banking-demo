using AuthorityService.LoanDecision.Contracts;
using AuthorityService.LoanDecision.Policy;

namespace AuthorityService.LoanDecision.Snapshots;

public sealed class LoanSnapshotBuilder(
    ILoanAuthoritativeSource authoritativeSource,
    LoanSnapshotValidator validator)
{
    public LoanDecisionSnapshotV1 BuildCanonical(LoanSnapshotRequestV1 request)
    {
        validator.ValidateRequest(request);
        var pages = authoritativeSource.Enumerate(new LoanAuthoritativeQueryV1
        {
            ApplicantId = request.Applicant.ApplicantId,
            ApplicationId = request.Application.ApplicationId,
            ActionId = request.Action.ActionId
        }) ?? throw new LoanSnapshotValidationException(
            LoanDecisionReasonCodes.AuthoritativeSourceUnavailable,
            "The authoritative source returned no enumeration.");

        var input = BuildInput(request, pages);
        validator.ValidateStructure(input);

        var action = new LoanActionBindingV1
        {
            ActionId = request.Action.ActionId,
            ApplicationId = request.Action.ApplicationId,
            ApplicantId = request.Action.ApplicantId,
            Payload = (Newtonsoft.Json.Linq.JObject)request.Action.Payload.DeepClone()
        };
        action.ActionDigest = LoanDecisionDigests.Action(action);

        var evidence = input.Evidence.OrderBy(item => item.EvidenceId, StringComparer.Ordinal).ToList();
        var snapshot = new LoanDecisionSnapshotV1
        {
            Applicant = request.Applicant,
            Application = request.Application,
            Action = action,
            PolicyVersion = request.PolicyVersion,
            Sources = input.Sources.OrderBy(item => item.SourceId, StringComparer.Ordinal).ToList(),
            Documents = input.Documents.OrderBy(item => item.DocumentId, StringComparer.Ordinal).ToList(),
            Evidence = evidence,
            Completeness = new LoanCompletenessResultV1
            {
                Status = input.Completeness.Status,
                MissingEvidenceIds = input.Completeness.MissingEvidenceIds.OrderBy(id => id, StringComparer.Ordinal).ToList(),
                Pagination = input.Completeness.Pagination.OrderBy(item => item.SourceId, StringComparer.Ordinal).ToList()
            },
            Freshness = input.Freshness.OrderBy(item => item.EvidenceId, StringComparer.Ordinal).ToList(),
            Contradictions = input.Contradictions
                .OrderBy(item => item.Code, StringComparer.Ordinal)
                .Select(item => new LoanContradictionResultV1
                {
                    Code = item.Code,
                    Status = item.Status,
                    EvidenceIds = item.EvidenceIds.OrderBy(id => id, StringComparer.Ordinal).ToList()
                }).ToList(),
            Facts = input.Facts
                .OrderBy(item => item.Name, StringComparer.Ordinal)
                .Select(item => new LoanNormalizedFactV1
                {
                    Name = item.Name,
                    Type = item.Type,
                    Value = item.Value,
                    EvidenceIds = item.EvidenceIds.OrderBy(id => id, StringComparer.Ordinal).ToList()
                }).ToList(),
            EvidenceDigests = evidence.ToDictionary(
                item => item.EvidenceId, LoanDecisionDigests.Evidence, StringComparer.Ordinal),
            AuthoritativeSourceDigest = string.Empty
        };
        snapshot = CopyWithAuthorityDigest(snapshot, LoanDecisionDigests.AuthoritativeSource(snapshot));
        snapshot.SnapshotDigest = LoanDecisionDigests.Snapshot(snapshot);
        return snapshot;
    }

    public LoanDecisionSnapshotV1 BuildForDecision(
        LoanSnapshotRequestV1 request,
        ResolvedLoanPolicy policy)
    {
        var snapshot = BuildCanonical(request);
        var current = BuildCanonical(request);
        if (!string.Equals(
                snapshot.AuthoritativeSourceDigest,
                current.AuthoritativeSourceDigest,
                StringComparison.Ordinal))
        {
            throw new LoanSnapshotValidationException(
                LoanDecisionReasonCodes.AuthoritativeSourceChanged,
                "Authoritative loan records changed after snapshot construction.");
        }

        validator.ValidateForDecision(snapshot, policy);
        return snapshot;
    }

    private static LoanSnapshotInputV1 BuildInput(
        LoanSnapshotRequestV1 request,
        IReadOnlyList<LoanAuthoritativePageV1> pages)
    {
        var orderedPages = pages
            .OrderBy(page => page.SourceId, StringComparer.Ordinal)
            .ThenBy(page => page.PageNumber)
            .ToList();
        foreach (var group in orderedPages.GroupBy(page => page.SourceId, StringComparer.Ordinal))
        {
            var first = group.First().Source;
            if (group.Any(page =>
                    page.SourceId != page.Source.SourceId ||
                    page.Source.RecordId != first.RecordId ||
                    page.Source.Version != first.Version ||
                    page.Source.Etag != first.Etag ||
                    page.Source.ApplicantId != first.ApplicantId ||
                    page.Source.ApplicationId != first.ApplicationId))
            {
                throw new LoanSnapshotValidationException(
                    LoanDecisionReasonCodes.BindingMismatch,
                    $"Authoritative pages for source '{group.Key}' disagree on identity or revision.");
            }
        }

        var records = orderedPages.SelectMany(page => page.Records).ToList();
        foreach (var documents in records.Where(record => record.Document is not null)
                     .Select(record => record.Document!)
                     .GroupBy(document => document.DocumentId, StringComparer.Ordinal))
        {
            var first = documents.First();
            if (documents.Any(document =>
                    document.SourceId != first.SourceId ||
                    document.SourceRecordId != first.SourceRecordId ||
                    document.Version != first.Version ||
                    document.Etag != first.Etag ||
                    document.ApplicantId != first.ApplicantId ||
                    document.ApplicationId != first.ApplicationId))
            {
                throw new LoanSnapshotValidationException(
                    LoanDecisionReasonCodes.BindingMismatch,
                    $"Authoritative document '{documents.Key}' has conflicting bindings.");
            }
        }
        var sources = orderedPages
            .GroupBy(page => page.SourceId, StringComparer.Ordinal)
            .Select(group => group.First().Source)
            .ToList();
        var evidence = records.Where(record => record.Evidence is not null)
            .Select(record => record.Evidence!).ToList();

        var pagination = orderedPages
            .GroupBy(page => page.SourceId, StringComparer.Ordinal)
            .Select(group =>
            {
                var sourcePages = group.OrderBy(page => page.PageNumber).ToList();
                var expectedPageNumbers = Enumerable.Range(1, sourcePages.Count);
                var tokensLink = sourcePages.Zip(sourcePages.Skip(1),
                    (current, next) => current.NextToken == next.RequestToken).All(value => value);
                var repeated = sourcePages
                    .SelectMany(page => new[] { page.RequestToken, page.NextToken })
                    .Where(token => token is not null)
                    .GroupBy(token => token, StringComparer.Ordinal)
                    .Any(tokens => tokens.Count() > 2);
                return new LoanPaginationProofV1
                {
                    SourceId = group.Key,
                    PageCount = sourcePages.Count,
                    RecordCount = sourcePages.Sum(page => page.Records.Count(record => record.Evidence is not null)),
                    Terminated = sourcePages.Select(page => page.PageNumber).SequenceEqual(expectedPageNumbers) &&
                                 tokensLink && sourcePages[^1].NextToken is null,
                    RepeatedToken = repeated
                };
            }).ToList();

        return new LoanSnapshotInputV1
        {
            Applicant = request.Applicant,
            Application = request.Application,
            Action = request.Action,
            PolicyVersion = request.PolicyVersion,
            Sources = sources,
            Documents = records.Where(record => record.Document is not null)
                .Select(record => record.Document!).DistinctBy(document => document.DocumentId).ToList(),
            Evidence = evidence,
            Completeness = new LoanCompletenessResultV1
            {
                Status = pages.Count > 0 && pagination.All(item => item.Terminated && !item.RepeatedToken)
                    ? LoanCompletenessStatus.Complete
                    : LoanCompletenessStatus.Incomplete,
                MissingEvidenceIds = [],
                Pagination = pagination
            },
            Freshness = records.Where(record => record.Freshness is not null)
                .Select(record => record.Freshness!).ToList(),
            Contradictions = records.SelectMany(record => record.Contradictions).ToList(),
            Facts = records.SelectMany(record => record.Facts).ToList()
        };
    }

    private static LoanDecisionSnapshotV1 CopyWithAuthorityDigest(
        LoanDecisionSnapshotV1 value,
        string digest) =>
        new()
        {
            Applicant = value.Applicant,
            Application = value.Application,
            Action = value.Action,
            PolicyVersion = value.PolicyVersion,
            Sources = value.Sources,
            Documents = value.Documents,
            Evidence = value.Evidence,
            Completeness = value.Completeness,
            Freshness = value.Freshness,
            Contradictions = value.Contradictions,
            Facts = value.Facts,
            EvidenceDigests = value.EvidenceDigests,
            AuthoritativeSourceDigest = digest
        };
}
