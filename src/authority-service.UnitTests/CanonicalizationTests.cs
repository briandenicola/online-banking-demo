using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests;

public class CanonicalizationTests
{
    private static readonly ResolvedPolicy Policy = TestHarness.LoadPolicy();

    private static ActionDefinition Action => new()
    {
        HashFields = ["transactionId", "amount", "decision"],
        MoneyFields = ["amount"]
    };

    private static string Hash(JObject payload, string? policyVersion = null) =>
        PayloadHasher.Compute(payload, Action, "transaction.flag.review",
            policyVersion ?? Policy.PolicyVersion, Policy.Document.Defaults.CurrencyScale);

    [Fact]
    public void Key_order_does_not_change_the_hash()
    {
        var a = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");
        var b = JObject.Parse("""{"decision":"cleared","amount":"10.00","transactionId":"t1"}""");

        Hash(a).Should().Be(Hash(b));
    }

    [Fact]
    public void Fields_outside_hashFields_do_not_change_the_hash()
    {
        var a = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");
        var b = (JObject)a.DeepClone();
        b["note"] = "an unsigned annotation";

        Hash(a).Should().Be(Hash(b));
    }

    [Fact]
    public void Money_is_compared_at_a_fixed_scale_not_as_text()
    {
        // "10.5" and "10.50" are the same amount. Canonicalizing money as a fixed-scale decimal
        // string means the hash agrees with arithmetic rather than with typography.
        var a = JObject.Parse("""{"transactionId":"t1","amount":"10.5","decision":"cleared"}""");
        var b = JObject.Parse("""{"transactionId":"t1","amount":"10.50","decision":"cleared"}""");

        Hash(a).Should().Be(Hash(b));
    }

    [Fact]
    public void A_different_amount_changes_the_hash()
    {
        var a = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");
        var b = JObject.Parse("""{"transactionId":"t1","amount":"10.01","decision":"cleared"}""");

        Hash(a).Should().NotBe(Hash(b));
    }

    [Fact]
    public void PolicyVersion_is_bound_into_the_hash()
    {
        // A signature produced under a permissive ruleset can never be presented as though it
        // had been produced under the current one (design §6.2.1).
        var payload = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");

        Hash(payload, "pv1:aaaaaaaaaaaaaaaa").Should().NotBe(Hash(payload, "pv1:bbbbbbbbbbbbbbbb"));
    }

    [Fact]
    public void The_action_id_is_bound_into_the_hash()
    {
        var payload = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");
        var scale = Policy.Document.Defaults.CurrencyScale;

        PayloadHasher.Compute(payload, Action, "transaction.flag.review", Policy.PolicyVersion, scale)
            .Should().NotBe(
                PayloadHasher.Compute(payload, Action, "transfer.reverse", Policy.PolicyVersion, scale));
    }

    [Fact]
    public void A_missing_hash_field_is_refused_rather_than_hashed_as_absent()
    {
        // Silently hashing an absent field would let "amount omitted" and "amount = 0" collide.
        var payload = JObject.Parse("""{"transactionId":"t1","decision":"cleared"}""");

        var act = () => Hash(payload);

        act.Should().Throw<CanonicalizationException>();
    }

    [Fact]
    public void A_floating_point_money_value_is_refused()
    {
        var payload = JObject.Parse("""{"transactionId":"t1","amount":10.1,"decision":"cleared"}""");

        var act = () => Hash(payload);

        act.Should().Throw<CanonicalizationException>();
    }

    [Fact]
    public void The_display_form_is_derived_from_the_full_hash()
    {
        var payload = JObject.Parse("""{"transactionId":"t1","amount":"10.00","decision":"cleared"}""");
        var hash = Hash(payload);

        var display = PayloadHasher.Short(hash);

        display.Should().MatchRegex("^[0-9a-f]{4} [0-9a-f]{4} [0-9a-f]{4} [0-9a-f]{4}$");
        display.Replace(" ", string.Empty).Should().Be(hash["sha256:".Length..][..16]);
    }
}
