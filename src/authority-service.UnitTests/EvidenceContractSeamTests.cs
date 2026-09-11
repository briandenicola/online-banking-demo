using AuthorityService.Policy;
using FluentAssertions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// The evidence contract seam.
///
/// Two documents have to agree and neither knows about the other:
///
///   <c>config/authority-policy.yaml</c>   evidence: &lt;toolId&gt;: requiredFields: [...]
///   <c>config/copilot-tools.yaml</c>      tools:    &lt;toolId&gt;: evidenceProjection: {...}
///
/// They were mutually unsatisfiable for the whole of Phase 3 and nothing failed, because every
/// check lived inside one file's own language. Six of six L2-reachable actions refused at propose
/// with <c>evidence_incomplete</c>, and the first thing that noticed was a human running a demo.
///
/// So this test runs the <b>real</b> <see cref="PolicyEvaluator"/>. It does not restate
/// <c>EvidenceComplete</c>, and it must not: a re-implementation here (in C# or, as first
/// proposed, in Python) would be a third document that can drift from both, and it would keep
/// passing on the day someone strengthens the real predicate. Every defect found on this repo
/// during Gate A/Gate B was correct within its own file and unheld across a boundary. This is
/// the hold.
///
/// <b>What this test does NOT prove.</b> The samples in
/// <c>tests/fixtures/evidence-samples/</c> are hand-built from the services' shipped response
/// types, not captured from a live run — the runs that would have captured them
/// (<c>run_5855e85caad34c12</c>, <c>run_5ed954af071b4ebc</c>) are the very runs that refused. So
/// this proves the two config documents are mutually satisfiable <i>against a recorded shape</i>.
/// It does <b>not</b> prove that account-service and transaction-service still return that shape.
/// That gap is real and closing it is a post-demo contract test against live services.
///
/// The other half of the join lives in
/// <c>src/banker-copilot-service/tests/test_evidence_projection.py</c>, which proves each
/// sample's <c>projected</c> block is what the shipped projection engine actually produces from
/// its <c>response</c> block. Two tests, each running one real component, joined by one
/// checked-in artifact; neither re-implements the other.
/// </summary>
public class EvidenceContractSeamTests
{
    private static readonly ResolvedPolicy Policy = TestHarness.LoadPolicy();
    private static readonly PolicyEvaluator Evaluator = new();

    /// <summary>
    /// Evidence keys deliberately NOT held yet, each with the reason it is exempt.
    ///
    /// A quarantine that is invisible becomes permanent, so every exemption is named here rather
    /// than expressed as a missing fixture. Fixing the upstream deletes the entry and the test
    /// starts holding that key automatically — there is nothing else to remember to do.
    /// </summary>
    private static readonly Dictionary<string, string> Quarantined = new()
    {
        ["list_login_audits"] =
            "Gate B ruling §R5. The policy requires [userId, count]; the upstream " +
            "(/api/admin/login-audits) filters by RECENCY ONLY, not by user, and the tool takes " +
            "no userId parameter. A projection could only produce userId by reading the proposal " +
            "payload, which would make the approval record assert 'here are user X's N recent " +
            "logins' when the truth is 'here are the last N logins of anybody at all'. That is a " +
            "false statement in an audit artifact about a security action. user.lock and " +
            "user.unlock therefore remain blocked at Gate B, knowingly. Honest exits: give the " +
            "upstream a userId filter (preferred), or correct the policy to what the tool can " +
            "supply. Both blocked at Gate A anyway.",

        ["get_user"] =
            "Gate B ruling §R6. The policy requires [userId, status]; the tool returns id and " +
            "isActive. userId <- rename id is fine, but 'status' is not a rename of a boolean: " +
            "isActive:true surfaced as 'status' reads as a state field carrying true, and a year " +
            "later nobody can tell whether that meant active, not-locked, or that the projection " +
            "did something clever. The fix is a POLICY correction to [userId, isActive], " +
            "sequenced with §R5. Deferred deliberately, not overlooked.",

        ["get_flagged_transaction"] =
            "Deferred by Gate B ruling §R8: out of the minimum scope, which is the two tools of " +
            "account.balance.adjust. No projection declared and no sample recorded yet.",

        ["get_scored_transaction"] =
            "Deferred by Gate B ruling §R8: out of the minimum scope. No projection declared yet.",

        ["get_transfer"] =
            "Deferred by Gate B ruling §R8: out of the minimum scope. No projection declared yet.",

        ["get_account_application"] =
            "Deferred by Gate B ruling §R8: out of the minimum scope. Blocked at Gate A as well.",

        ["get_application_audit"] =
            "Deferred by Gate B ruling §R8: out of the minimum scope. Blocked at Gate A as well."
    };

    /// <summary>
    /// Evidence keys whose services do not exist yet. Declared inert rather than silently
    /// skipped: an unimplemented service that vanishes from a test looks exactly like one that
    /// passes.
    /// </summary>
    private static readonly Dictionary<string, string> DeclaredInert = new()
    {
        ["get_loan_application"] =
            "loan-origination-service has not shipped, so there is no endpoint to record a " +
            "sample from and no tool in the manifest. Declared inert rather than skipped: when " +
            "the service lands, delete this entry and the seam test demands a projection and a " +
            "fixture before loan.decision.record can be proposed.",

        ["get_underwriting_decision"] =
            "loan-origination-service has not shipped; see get_loan_application. Named here so " +
            "that an unimplemented service cannot be mistaken for a passing one.",

        ["get_policy_evaluation"] =
            "loan-origination-service has not shipped; see get_loan_application. Its " +
            "requiredFields include policyExceptions, which drives an escalator, so this one " +
            "must not be quietly waved through when the service arrives."
    };

    // ---------------------------------------------------------------------------------

    private static string RepoRoot
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);

            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "config", "copilot-tools.yaml")))
                    return directory.FullName;

                directory = directory.Parent;
            }

            throw new FileNotFoundException("Could not locate the repository root from the test output.");
        }
    }

    private static JObject? Sample(string toolId)
    {
        var path = Path.Combine(RepoRoot, "tests", "fixtures", "evidence-samples", $"{toolId}.json");

        return File.Exists(path) ? JObject.Parse(File.ReadAllText(path)) : null;
    }

    /// <summary>The manifest's tool ids, read from the file the copilot service actually loads.</summary>
    private static HashSet<string> ManifestToolIds()
    {
        var yaml = File.ReadAllText(Path.Combine(RepoRoot, "config", "copilot-tools.yaml"));
        var ids = new HashSet<string>(StringComparer.Ordinal);

        foreach (var line in yaml.Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("- toolId:", StringComparison.Ordinal))
                ids.Add(trimmed["- toolId:".Length..].Trim());
        }

        return ids;
    }

    /// <summary>
    /// The text of one tool's block in the manifest, or null if the tool is absent. Deliberately
    /// textual: this test asserts what the manifest DECLARES, and reading it through a parser
    /// that shares assumptions with the loader would weaken that.
    /// </summary>
    private static string? ToolBlock(string toolId)
    {
        var text = File.ReadAllText(Path.Combine(RepoRoot, "config", "copilot-tools.yaml"));
        var start = text.IndexOf($"- toolId: {toolId}", StringComparison.Ordinal);

        if (start < 0) return null;

        var next = text.IndexOf("- toolId:", start + 5, StringComparison.Ordinal);

        return next < 0 ? text[start..] : text[start..next];
    }

    private static string? ProjectionBlockFor(string toolId)
    {
        var block = ToolBlock(toolId);

        if (block is null) return null;

        var at = block.IndexOf("evidenceProjection:", StringComparison.Ordinal);

        return at < 0 ? null : block[at..];
    }

    /// <summary>
    /// Runs the REAL evaluator and reports the evidence gaps it found. Everything below asserts
    /// on this and nothing else — no local notion of "complete" exists in this file.
    /// </summary>
    private static IReadOnlyList<string> EvidenceGaps(string actionId, JObject evidence)
    {
        var decision = Evaluator.Evaluate(new EvaluationContext
        {
            ActionId = actionId,
            Payload = new JObject { ["accountId"] = "acct-1001", ["amount"] = "10.00" },
            Actor = TestHarness.Banker(),
            Evidence = evidence
        }, Policy);

        return decision.EvidenceGaps ?? [];
    }

    private static IEnumerable<(string ActionId, string Key)> ContractPairs() =>
        Policy.Document.ActionTypes
              .SelectMany(action => action.Value.RequiredEvidence
                                          .Select(key => (action.Key, key)))
              .OrderBy(pair => pair.Key, StringComparer.Ordinal);

    // ---------------------------------------------------------------------------------

    [Fact]
    public void Every_evidence_key_named_by_an_action_is_defined_declared_inert_or_quarantined()
    {
        var manifest = ManifestToolIds();
        var unaccounted = new List<string>();

        foreach (var (actionId, key) in ContractPairs())
        {
            Policy.Document.Evidence.Should().ContainKey(key,
                $"action '{actionId}' requires evidence '{key}', which no evidence: block defines");

            if (Quarantined.ContainsKey(key) || DeclaredInert.ContainsKey(key)) continue;

            if (!manifest.Contains(key)) unaccounted.Add($"{actionId} -> {key}: no tool in the manifest");
            else if (Sample(key) is null) unaccounted.Add($"{actionId} -> {key}: no recorded sample");
        }

        unaccounted.Should().BeEmpty(
            "an evidence key must either be held by this test or exempted BY NAME WITH A REASON. " +
            "Add a fixture, or add a Quarantined/DeclaredInert entry saying why not");
    }

    /// <summary>
    /// The whole point. Projected sample in, REAL EvidenceComplete over it, no gap out.
    /// </summary>
    [Fact]
    public void The_declared_projection_satisfies_the_policy_for_every_held_key()
    {
        var held = 0;

        foreach (var (actionId, key) in ContractPairs())
        {
            if (Quarantined.ContainsKey(key) || DeclaredInert.ContainsKey(key)) continue;

            var sample = Sample(key);
            sample.Should().NotBeNull($"'{key}' is held but has no sample");

            var projected = sample!["projected"] as JObject;
            projected.Should().NotBeNull(
                $"'{key}' sample has no projected object; regenerate with " +
                "scripts/demo/evidence-contract.py . --samples --write");

            // Read from the manifest text, not from the fixture, so that DELETING a projection
            // fails here rather than only in the Python fixture test. A checked-in artifact must
            // not be the only witness to the declaration that produced it.
            ProjectionBlockFor(key).Should().NotBeNullOrWhiteSpace(
                $"'{key}' is held by this test but declares no evidenceProjection in " +
                "copilot-tools.yaml; the fixture would then be the only thing asserting the shape");

            EvidenceGaps(actionId, new JObject { [key] = projected })
                .Should().NotContain(key,
                    $"the projection declared for '{key}' in copilot-tools.yaml must satisfy the " +
                    $"requiredFields declared for it in authority-policy.yaml " +
                    $"({string.Join(", ", Policy.Document.Evidence[key].RequiredFields)})");

            held++;
        }

        // Absent by coincidence is the failure mode this repo keeps producing: a test that holds
        // nothing still reports success. If the contract is ever rewritten so that no key is held,
        // this test must fail rather than quietly become an empty loop.
        held.Should().BeGreaterThan(0, "this test must actually be holding something");
    }

    /// <summary>
    /// The negative control, and the reason the test above is not passing for free.
    ///
    /// The RAW recorded response must FAIL the very check its projection passes. Without this, a
    /// policy whose requiredFields were emptied — or a projection that did nothing at all — would
    /// sail through: every assertion above would hold for the wrong reason.
    /// </summary>
    [Fact]
    public void The_raw_response_does_not_satisfy_the_policy_which_is_why_a_projection_exists()
    {
        var proven = 0;

        foreach (var (actionId, key) in ContractPairs())
        {
            if (Quarantined.ContainsKey(key) || DeclaredInert.ContainsKey(key)) continue;

            var sample = Sample(key)!;
            var raw = sample["response"]!;

            Policy.Document.Evidence[key].RequiredFields.Should().NotBeEmpty(
                $"'{key}' would be satisfied by anything if its requiredFields were empty, and " +
                "the completeness check would be a control that can never fail");

            var evidence = new JObject { [key] = raw };

            EvidenceGaps(actionId, evidence).Should().Contain(key,
                $"the RAW '{key}' response must be insufficient — if it already satisfied the " +
                "policy, the projection would be decoration and this suite would be proving " +
                "nothing about it");

            proven++;
        }

        proven.Should().BeGreaterThan(0, "this test must actually be holding something");
    }

    /// <summary>
    /// Projection is lossless: it may add and rename, never drop. An approval record that could
    /// be trimmed by the party seeking approval is an exhibit, not a record.
    /// </summary>
    [Fact]
    public void Projection_never_drops_material_the_service_returned()
    {
        foreach (var (_, key) in ContractPairs())
        {
            if (Quarantined.ContainsKey(key) || DeclaredInert.ContainsKey(key)) continue;

            var sample = Sample(key)!;
            var raw = sample["response"]!;
            var projected = (JObject)sample["projected"]!;

            if (raw is JArray array)
            {
                projected.Properties()
                         .Any(p => p.Value is JArray carried && JToken.DeepEquals(carried, array))
                         .Should().BeTrue($"'{key}' projects an array response but does not carry it whole");
            }
            else
            {
                foreach (var property in ((JObject)raw).Properties())
                {
                    projected.Should().ContainKey(property.Name,
                        $"'{key}' projection dropped '{property.Name}'");
                    JToken.DeepEquals(projected[property.Name]!, property.Value)
                          .Should().BeTrue($"'{key}' projection altered '{property.Name}'");
                }
            }
        }
    }

    /// <summary>
    /// user.lock and user.unlock are blocked at Gate B ON THE RECORD, not by omission. If someone
    /// later declares a projection for list_login_audits, this test fails and forces them to read
    /// §R5 before the demo can start asserting whose logins those were.
    /// </summary>
    [Fact]
    public void The_quarantined_keys_are_still_quarantined_and_still_explained()
    {
        foreach (var (key, reason) in Quarantined.Concat(DeclaredInert))
        {
            reason.Length.Should().BeGreaterThan(60,
                $"'{key}' is exempt without a usable reason; an unexplained quarantine becomes permanent");

            Sample(key).Should().BeNull(
                $"'{key}' is quarantined but now has a recorded sample. If the underlying problem " +
                "is fixed, delete its entry from Quarantined/DeclaredInert so this suite starts " +
                "holding it — do not leave a fixture sitting behind an exemption.");
        }

        // Specifically, and by name, because this one would be a lie rather than a gap:
        ProjectionBlockFor("list_login_audits").Should().BeNull(
            "list_login_audits must have NO projection (§R5): the upstream filters by recency, " +
            "not by user, so any userId it emitted would be fabricated from the proposal payload");
    }

    /// <summary>
    /// §R3.3: an approval record must be joinable to the run that produced it. The ratified
    /// requirement is that evidence rows deep-link back to the originating trace node, and a
    /// projected object with no path back to the call that produced it cannot satisfy that.
    ///
    /// Both ids were already carried end to end — `propose.py` puts `sessionId` in the body and
    /// `X-Correlation-ID` on the header, and `ApprovalService` writes both onto the record — so
    /// no schema change was needed. But nothing HELD it, and "correct in its own file, unheld
    /// across the boundary" is precisely the defect this whole ruling exists to stop. Held now.
    /// </summary>
    [Fact]
    public async Task An_approval_is_joinable_to_the_run_that_produced_it()
    {
        var harness = TestHarness.Build();

        var approval = await harness.Service.ProposeAsync(
            TestHarness.FlagReview("100.00"),
            TestHarness.Banker(sessionId: "sess-1"),
            correlationId: "corr-abc123");

        approval.SessionId.Should().Be("sess-1",
            "without the session id the approval cannot be joined to its trace");
        approval.CorrelationId.Should().Be("corr-abc123",
            "without the correlation id the evidence cannot be traced to the tool calls that produced it");
    }
}
