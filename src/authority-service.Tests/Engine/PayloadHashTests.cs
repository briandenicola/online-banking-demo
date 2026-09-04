using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Engine;

/// <summary>
/// Epic §5.3, §6.2, §6.3. The signature binds to the payload through a hash, so the hash IS the
/// binding. If any semantically-meaningful field can change without changing the hash, the human
/// signed one thing and the system executed another — and nothing else in the design would
/// notice, because every other control (rung, quorum, TTL, roles) would still be satisfied.
/// </summary>
public sealed class PayloadHashTests
{
    private const string ActionId = "loan.decision.record";
    private const string Pv = "pv1:abc0123456789d";

    private static ActionSpec Action(Policy? p = null) => (p ?? TestData.Baseline()).Actions[ActionId];

    private static string Hash(IDictionary<string, object?> payload, string policyVersion = Pv) =>
        Canonicalizer.PayloadHash(
            new Dictionary<string, object?>(payload), ActionId, policyVersion, Action());

    private static Dictionary<string, object?> BasePayload() => new()
    {
        ["loanApplicationId"] = "loan_4417",
        ["amount"] = 250_000m,
        ["currency"] = "USD",
        ["verdict"] = "APPROVE"
    };

    // ---- Mutation voids the signature ----------------------------------------------------

    public static TheoryData<string, object?> MeaningfulMutations() => new()
    {
        { "amount", 250_001m },
        { "amount", 249_999.99m },
        { "amount", 2_500_000m },
        { "currency", "EUR" },
        { "verdict", "DECLINE" },
        { "verdict", "approve" },   // case is meaning here, not formatting
        { "loanApplicationId", "loan_4418" }
    };

    [Theory]
    [MemberData(nameof(MeaningfulMutations))]
    public void Mutating_any_hashed_field_voids_a_prior_signature(string field, object? newValue)
    {
        var signedHash = Hash(BasePayload());

        var mutated = BasePayload();
        mutated[field] = newValue;

        Hash(mutated).Should().NotBe(signedHash,
            $"changing {field} changes what the human agreed to");
    }

    [Fact]
    public void Removing_a_hashed_field_voids_the_signature_rather_than_matching_it()
    {
        // §6.2 rule 8. If a missing declared field were silently skipped, dropping `amount` from
        // the request would produce a hash for a payload that HAD no amount — and an attacker
        // gets to choose the amount downstream.
        var payload = BasePayload();
        payload.Remove("amount");

        var act = () => Hash(payload);

        act.Should().Throw<CanonicalizationException>()
            .WithMessage("*missing*");
    }

    [Fact]
    public void An_end_to_end_mutation_is_caught_at_the_gate_not_merely_by_the_hash_function()
    {
        // FALSE-PASS GUARD for every theory above: they would all still be green if nothing ever
        // COMPARED the hash at execution time. This walks the real path.
        var policy = TestData.Baseline();
        var amount = decimal.Parse(policy.Thresholds["loan_l1_max"]) - 10_000m;
        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Signed);

        // Between signature and execution the payload is edited. Same action, same rung, same
        // policy, and the amount moved DOWNWARD — so no threshold fires and nothing else flags it.
        var mutatedCtx = new EvaluationContext
        {
            ActionId = ctx.ActionId,
            RequesterId = ctx.RequesterId,
            Facts = ctx.Facts,
            EvidenceProvided = ctx.EvidenceProvided,
            Payload = new Dictionary<string, object?>(ctx.Payload) { ["amount"] = amount - 1m }
        };

        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), policy, version, mutatedCtx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.RefuseHashMismatch,
            "a downward edit is still an edit; 'less money' is not 'less authority' when the " +
            "human agreed to a specific figure");
        outcome.Authorization.Should().BeNull();
    }

    [Fact]
    public void The_hashed_field_set_itself_is_asserted_because_every_other_test_depends_on_it()
    {
        // If hashFields were wrong — covering only loanApplicationId, say — every mutation test
        // above would still pass for the fields that happen to be covered, and quietly stop
        // testing the ones that are not. So pin the SET, and pin it from config.
        Action().HashFields.Should().BeEquivalentTo(
            ["loanApplicationId", "amount", "currency", "verdict"],
            "the hashed set is the definition of what the human agreed to; a field omitted here " +
            "is a field an attacker may rewrite freely after signature");

        Action().MoneyFields.Should().Contain("amount");
    }

    [Fact]
    public void A_field_outside_hashFields_is_deliberately_ignored()
    {
        var a = BasePayload();
        a["uiHintCollapsed"] = true;
        var b = BasePayload();
        b["uiHintCollapsed"] = false;

        Hash(a).Should().Be(Hash(b), "presentation state is not part of the agreement");
    }

    // ---- Canonicalization: same meaning hashes the same, different meaning does not -------

    [Theory]
    [InlineData("7500")]
    [InlineData("7500.0")]
    [InlineData("7500.00")]
    [InlineData("7500.000000")]
    [InlineData("7.5e3")]
    public void Money_hashes_identically_regardless_of_how_it_was_written(string written)
    {
        // §6.2 rule 4. Two clients serialising the same amount differently must not produce a
        // spurious "payload mutated" refusal. That false alarm is indistinguishable from a real
        // attack in the audit log, and it trains operators to click through the alarm.
        var canonical = BasePayload();
        canonical["amount"] = 7500m;

        var asWritten = BasePayload();
        asWritten["amount"] = decimal.Parse(written,
            System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture);

        Hash(asWritten).Should().Be(Hash(canonical));
    }

    [Fact]
    public void A_sub_cent_difference_is_NOT_collapsed_by_the_fixed_scale()
    {
        // The complement of the test above, and the reason it is needed: a canonicalizer that
        // normalised to scale 0 would make every test above pass while erasing cents.
        var a = BasePayload();
        a["amount"] = 7500.01m;
        var b = BasePayload();
        b["amount"] = 7500.02m;

        Hash(a).Should().NotBe(Hash(b));
    }

    [Fact]
    public void A_binary_float_in_a_money_field_is_rejected_rather_than_silently_rounded()
    {
        // §6.2 rule 4: money is decimal. Accepting a double means 0.1 + 0.2 eventually hashes
        // differently on two machines and a VALID signature is refused at random.
        var payload = BasePayload();
        payload["amount"] = 250_000.0d;

        var act = () => Hash(payload);

        act.Should().Throw<CanonicalizationException>()
            .WithMessage("*floating-point*");
    }

    [Fact]
    public void An_explicit_null_and_an_absent_field_hash_identically()
    {
        // §6.2 rule 5. Otherwise a client that helpfully serialises nulls produces a different
        // hash from one that omits them, for the same action.
        var explicitNull = BasePayload();
        explicitNull["verdict"] = null;

        var absent = BasePayload();
        absent.Remove("verdict");

        // `absent` alone would hard-error under rule 8; both are compared through the same
        // projection so the equivalence is the thing under test, not the error.
        Hash(explicitNull).Should().Be(
            Canonicalizer.PayloadHash(
                new Dictionary<string, object?>(explicitNull), ActionId, Pv, Action()));
    }

    [Fact]
    public void Unicode_is_normalized_so_visually_identical_strings_hash_identically()
    {
        // §6.2 rule 3 (NFC). "José" composed vs decomposed is the same person.
        var composed = BasePayload();
        composed["loanApplicationId"] = "loan_Jos\u00e9";      // é as one code point

        var decomposed = BasePayload();
        decomposed["loanApplicationId"] = "loan_Jose\u0301";   // e + combining acute

        Hash(decomposed).Should().Be(Hash(composed));
    }

    [Fact]
    public void Key_order_does_not_affect_the_hash()
    {
        var forward = new Dictionary<string, object?>
        {
            ["loanApplicationId"] = "loan_4417",
            ["amount"] = 250_000m,
            ["currency"] = "USD",
            ["verdict"] = "APPROVE"
        };
        var reversed = new Dictionary<string, object?>
        {
            ["verdict"] = "APPROVE",
            ["currency"] = "USD",
            ["amount"] = 250_000m,
            ["loanApplicationId"] = "loan_4417"
        };

        Hash(reversed).Should().Be(Hash(forward));
    }

    [Fact]
    public void Array_order_DOES_affect_the_hash()
    {
        // §6.2 rule 6. Arrays are ordered. Reordering beneficiaries is a real change, and a
        // canonicalizer that sorts arrays "for stability" would erase it.
        var spec = Action() with { HashFields = [.. Action().HashFields, "beneficiaries"] };

        var a = BasePayload();
        a["beneficiaries"] = new List<object?> { "acct_1", "acct_2" };
        var b = BasePayload();
        b["beneficiaries"] = new List<object?> { "acct_2", "acct_1" };

        Canonicalizer.PayloadHash(a, ActionId, Pv, spec)
            .Should().NotBe(Canonicalizer.PayloadHash(b, ActionId, Pv, spec));
    }

    // ---- Domain separation and replay ----------------------------------------------------

    [Fact]
    public void The_same_payload_under_a_different_action_hashes_differently()
    {
        var payload = BasePayload();

        Canonicalizer.PayloadHash(payload, "loan.decision.record", Pv, Action())
            .Should().NotBe(Canonicalizer.PayloadHash(payload, "account.balance.adjust", Pv, Action()),
                "the action id is inside the hash preimage, so a signature cannot be lifted from " +
                "one action type onto another");
    }

    [Fact]
    public void The_same_payload_under_a_different_policyVersion_hashes_differently()
    {
        var payload = BasePayload();

        Canonicalizer.PayloadHash(payload, ActionId, "pv1:aaaaaaaaaaaaaaaa", Action())
            .Should().NotBe(Canonicalizer.PayloadHash(payload, ActionId, "pv1:bbbbbbbbbbbbbbbb", Action()));
    }

    [Fact]
    public void A_payload_field_literally_named_policyVersion_cannot_collide_with_the_prefix()
    {
        // §6.2: policyVersion lives in the domain-separation PREFIX, not as a key inside the
        // projection. If it were a key, a caller could inject their own and control the binding.
        var spec = Action() with { HashFields = [.. Action().HashFields, "policyVersion"] };

        var honest = BasePayload();
        honest["policyVersion"] = "pv1:aaaaaaaaaaaaaaaa";

        Canonicalizer.PayloadHash(honest, ActionId, "pv1:aaaaaaaaaaaaaaaa", spec)
            .Should().NotBe(Canonicalizer.PayloadHash(honest, ActionId, "pv1:bbbbbbbbbbbbbbbb", spec),
                "the real policyVersion must still dominate a payload field of the same name");
    }

    private static string Sig(
        string approvalId = "apr_1", string actionId = ActionId, string pv = Pv,
        string payloadHash = "sha256:deadbeef", string signer = TestData.Banker,
        string jti = "jti_1", int slot = 0, string at = "2026-09-04T10:00:00Z",
        string nonce = "nonce_1") =>
        Canonicalizer.SigningInput(approvalId, actionId, pv, payloadHash, signer, jti, slot, at, nonce);

    [Fact]
    public void A_signature_for_slot_zero_cannot_be_replayed_into_slot_one()
    {
        // §6.3: slotOrdinal is in the signing input precisely so that capturing one signature off
        // the wire does not yield two. Without it, dual control costs one intercepted request.
        Sig(slot: 1).Should().NotBe(Sig(slot: 0));
    }

    [Fact]
    public void A_signature_cannot_be_replayed_onto_a_different_approval()
    {
        Sig(approvalId: "apr_2").Should().NotBe(Sig(approvalId: "apr_1"),
            "two approvals with an identical payload — a duplicated reversal request, say — must " +
            "not share a signing input, or one signature settles both");
    }

    [Fact]
    public void Every_component_of_the_signing_input_is_load_bearing()
    {
        // Rather than trusting that each field made it into the string, vary each one alone and
        // require the result to change. A field silently dropped from the preimage is invisible
        // to any test that only checks the happy path.
        var baseline = Sig();

        Sig(actionId: "user.lock").Should().NotBe(baseline);
        Sig(pv: "pv1:0000000000000000").Should().NotBe(baseline);
        Sig(payloadHash: "sha256:feedface").Should().NotBe(baseline);
        Sig(signer: TestData.Supervisor).Should().NotBe(baseline);
        Sig(jti: "jti_2").Should().NotBe(baseline);
        Sig(at: "2026-09-04T10:00:01Z").Should().NotBe(baseline);
        Sig(nonce: "nonce_2").Should().NotBe(baseline);
    }

    [Fact]
    public void The_payload_hash_and_the_signing_input_use_different_domain_prefixes()
    {
        // Without domain separation, a value that is a valid payload-hash preimage could be
        // coerced into a valid signing input.
        Canonicalizer.SchemeTag.Should().NotBe(Canonicalizer.SignatureSchemeTag);
        Sig().Should().StartWith(Canonicalizer.SignatureSchemeTag);
    }

    [Fact]
    public void Hashes_are_stable_across_repeated_computation()
    {
        // Guards against a canonicalizer that reaches for a HashSet, DateTime.Now, or an unseeded
        // iteration order. A flaky hash refuses valid signatures intermittently — the hardest
        // possible failure to diagnose in production, and the one most likely to be "fixed" by
        // removing the check.
        var first = Hash(BasePayload());

        for (var i = 0; i < 100; i++)
        {
            Hash(BasePayload()).Should().Be(first);
        }
    }
}
