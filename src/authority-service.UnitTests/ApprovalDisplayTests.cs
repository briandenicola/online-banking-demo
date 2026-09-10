using AuthorityService.Contracts;
using AuthorityService.Models;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;

namespace AuthorityService.UnitTests;

public class ApprovalDisplayTests
{
    [Fact]
    public void Response_enriches_evidence_with_label_and_summary()
    {
        var approval = TestApproval();
        approval.Evidence = new JObject
        {
            ["get_user"] = new JObject
            {
                ["userId"] = "ffe7fb22-4430-4388-ac2b-d803d13453ff",
                ["firstName"] = "Dana",
                ["lastName"] = "Retail",
                ["status"] = "locked"
            },
            ["list_login_audits"] = new JObject
            {
                ["count"] = 4
            }
        };

        var response = ApprovalResponse.From(approval);

        response.Evidence["get_user"]!["label"]!.Value<string>().Should().Be("Customer record");
        response.Evidence["get_user"]!["summary"]!.Value<string>().Should().Be("Dana Retail is locked");
        response.Evidence["list_login_audits"]!["label"]!.Value<string>().Should().Be("Login history");
        response.Evidence["list_login_audits"]!["summary"]!.Value<string>().Should().Be("4 failed sign-in records");
    }

    [Fact]
    public void User_actions_get_a_person_subject_when_evidence_contains_the_customer()
    {
        var approval = TestApproval("user.unlock");
        approval.Payload = new JObject { ["userId"] = "ffe7fb22-4430-4388-ac2b-d803d13453ff" };
        approval.Evidence = new JObject
        {
            ["get_user"] = new JObject
            {
                ["userId"] = "ffe7fb22-4430-4388-ac2b-d803d13453ff",
                ["displayName"] = "Dana Retail",
                ["riskTier"] = "high",
                ["status"] = "locked"
            }
        };

        var response = ApprovalResponse.From(approval);

        response.Subject.Should().NotBeNull();
        response.Subject!.Kind.Should().Be("customer");
        response.Subject.Label.Should().Be("Dana Retail");
        response.Subject.Summary.Should().Be("Status: locked");
        response.Subject.UserId.Should().Be("ffe7fb22-4430-4388-ac2b-d803d13453ff");
        response.Subject.RiskTier.Should().Be("high");
    }

    [Fact]
    public void Account_actions_get_an_account_subject_from_existing_evidence()
    {
        var approval = TestApproval("account.balance.adjust");
        approval.Payload = new JObject { ["accountId"] = "acct-abc-1234" };
        approval.Evidence = new JObject
        {
            ["get_account"] = new JObject
            {
                ["accountId"] = "acct-abc-1234",
                ["accountNumber"] = "00001234",
                ["accountType"] = "Checking",
                ["balance"] = 59480
            }
        };

        var response = ApprovalResponse.From(approval);

        response.Subject.Should().NotBeNull();
        response.Subject!.Kind.Should().Be("account");
        response.Subject.Label.Should().Be("Checking account ····1234");
        response.Subject.Summary.Should().Be("Balance $59480.00");
        response.Subject.AccountId.Should().Be("acct-abc-1234");
        response.Subject.AccountType.Should().Be("Checking");
    }

    [Fact]
    public void Display_enrichment_does_not_mutate_stored_evidence_or_payload()
    {
        var approval = TestApproval("account.balance.adjust");
        approval.Payload = new JObject { ["accountId"] = "acct-1", ["amount"] = "35.00" };
        approval.Evidence = new JObject
        {
            ["get_account"] = new JObject { ["accountId"] = "acct-1", ["balance"] = "100.00" }
        };

        _ = ApprovalResponse.From(approval);

        approval.Payload["label"].Should().BeNull();
        approval.Evidence["get_account"]!["label"].Should().BeNull();
        approval.Evidence["get_account"]!["summary"].Should().BeNull();
    }

    private static Approval TestApproval(string actionId = "user.unlock") => new()
    {
        Id = "apr-test",
        ActionId = actionId,
        ActionLabel = actionId,
        RequesterId = "banker-1",
        PayloadHash = "sha256:abcdef",
        PolicyVersion = "test",
        PolicyId = "test-policy",
        BaseRung = Rung.L1,
        RequiredRung = Rung.L1,
        RequiredSigners = 1,
        MinSeniority = 1,
        ExpiresAt = DateTime.UtcNow.AddMinutes(10),
        Execution = new ExecutionRecord()
    };
}
