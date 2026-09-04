using AuthorityService.Models;
using FluentAssertions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// The stored document shape is a ratified contract, not an implementation detail. Rusty's
/// Cosmos indexes and the Python read path both address these paths by name, and a Cosmos path
/// mismatch returns ZERO ROWS rather than an error — "the supervisor's inbox is empty" would be
/// indistinguishable from "there is nothing to approve". So the shape is asserted here.
/// </summary>
public class ApprovalDocumentShapeTests
{
    private static JObject Serialize()
    {
        var approval = new Approval
        {
            Id = SharedIdentifiers.ApprovalIdPrefix + "0123456789abcdef01234567",
            RequesterId = "banker-1",
            ActionId = "transaction.flag.review",
            PolicyVersion = "pv1:deadbeefdeadbeef",
            PolicyId = "banker-copilot-authority",
            RequiredRung = Rung.L2,
            BaseRung = Rung.L1,
            RequiredSigners = 2,
            Status = ApprovalStatus.Pending
        };

        return JObject.Parse(JsonConvert.SerializeObject(approval));
    }

    [Fact]
    public void Policy_derived_fields_are_nested_under_policy()
    {
        var doc = Serialize();

        doc["policy"].Should().NotBeNull();
        doc["policy"]!["policyVersion"]!.Value<string>().Should().Be("pv1:deadbeefdeadbeef");
        doc["policy"]!["requiredRung"]!.Value<string>().Should().Be("L2");
        doc["policy"]!["baseRung"]!.Value<string>().Should().Be("L1");
        doc["policy"]!["requiredSigners"]!.Value<int>().Should().Be(2);
    }

    [Fact]
    public void PolicyVersion_appears_exactly_once_in_the_document()
    {
        var json = JsonConvert.SerializeObject(Serialize());

        // Epic §5.3.1: single definition. A second copy is a second thing that can be stale.
        var occurrences = json.Split("\"policyVersion\"").Length - 1;

        occurrences.Should().Be(1);
        JObject.Parse(json)["policyVersion"].Should().BeNull(
            "the façade properties are convenience for call sites and must not reach the wire");
    }

    [Fact]
    public void Fields_the_indexes_address_stay_at_the_top_level()
    {
        var doc = Serialize();

        // These exact paths appear in infra/cloud/cosmos.tf composite indexes.
        foreach (var path in new[] { "status", "createdAt", "expiresAtEpoch", "requesterId" })
        {
            doc[path].Should().NotBeNull($"'{path}' is indexed by name at the top level");
        }
    }

    [Fact]
    public void The_document_round_trips_through_serialization()
    {
        var json = JsonConvert.SerializeObject(Serialize());
        var back = JsonConvert.DeserializeObject<Approval>(json)!;

        back.PolicyVersion.Should().Be("pv1:deadbeefdeadbeef");
        back.RequiredRung.Should().Be(Rung.L2);
        back.RequiredSigners.Should().Be(2);
    }
}
