using AuthorityService.Policy;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Engine;

/// <summary>
/// Phase 3, separation-of-duties re-attacked from a FRESH angle. The existing
/// <c>SeparationOfDutiesTests</c> attack the signature store — two humans, one identity, admin at
/// the slot. This suite attacks one rung lower: the loader's cross-file agreement between the
/// shipping <c>authority-policy.yaml</c> and the ratified <c>role-hierarchy.yaml</c>. That check
/// is Turk's fail-closed fix for the two Phase 1 escalations (my <c>banker.claimValues</c>
/// included <c>user</c>; the coordinator's <c>admin</c> sat above supervisor and inside
/// <c>L2.cosignerRoles</c>). I re-run both original attacks against the real config, plus the
/// re-encoding vector (learning #2: a test/config that restates the vulnerable ascending model).
///
/// Every test tampers the REAL shipping YAML — never a fixture — and every test first proves the
/// UNtampered config loads clean, so a green result means "the tamper is what broke it", not "it
/// was already broken for some other reason" (the wrong-reason false pass).
/// </summary>
public sealed class RoleModelDivergenceTests
{
    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private static string PolicyYaml() =>
        File.ReadAllText(Path.Combine(RepoRoot(), "config", "authority-policy.yaml"));

    private static RoleHierarchy RatifiedHierarchy() =>
        RoleHierarchy.LoadFromYaml(
            File.ReadAllText(Path.Combine(RepoRoot(), "src", "user-service", "config", "role-hierarchy.yaml")),
            "role-hierarchy.yaml");

    private static void Load(string yaml) =>
        new PolicyLoader(new Dictionary<string, string?>(), RatifiedHierarchy())
            .LoadFromYaml(yaml, "<divergence-test>");

    // Fully wires `admin` as a declared signer role AND places it in the L2 cosigner slot, so the
    // ONLY thing that can stop it is the banking-seniority floor — not the "undeclared role" check
    // that trips first on a half-wired tamper. This is the true shape of the Phase 1 escalation:
    // admin was a first-class signer role, not a typo.
    private static string WireAdminAsCosigner(string yaml) =>
        yaml.Replace(
                "  supervisor:\n    claimValues: [supervisor, Supervisor]",
                "  supervisor:\n    claimValues: [supervisor, Supervisor]\n  admin:\n    claimValues: [admin, Admin]")
            .Replace("cosignerRoles: [supervisor]", "cosignerRoles: [supervisor, admin]");

    // ---- Positive control: the shipping pair agrees and starts ------------------------------

    [Fact]
    public void The_shipping_policy_and_the_ratified_hierarchy_agree()
    {
        // If this ever fails, every tamper test below is proving nothing — they would all throw
        // for a reason that has nothing to do with their tamper.
        var act = () => Load(PolicyYaml());
        act.Should().NotThrow(
            "the shipping authority-policy.yaml must load against the ratified role hierarchy, " +
            "or the divergence tests are asserting against an already-broken baseline");
    }

    // ---- Re-attack #1 (mine, Phase 1): a retail claim mapped onto a banking role -------------

    [Fact]
    public void A_customer_claim_mapped_onto_banker_is_refused()
    {
        // Phase 1: banker.claimValues contained `user`, so every retail customer's token filled an
        // L1 slot. The loader now requires a claim to spell only its own role.
        var tampered = PolicyYaml().Replace(
            "claimValues: [banker, Banker]",
            "claimValues: [banker, Banker, user]");
        tampered.Should().Contain(", user]", "the tamper must actually inject the customer claim");

        var act = () => Load(tampered);
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>()
            .WithMessage("*claimValues*user*");
    }

    // ---- Re-attack #2 (coordinator, Phase 1): admin given a banking signature slot -----------

    [Fact]
    public void Admin_added_to_the_L2_cosigner_list_is_refused()
    {
        // Phase 1: admin sat in L2.cosignerRoles as a first-class signer role. admin carries banking
        // seniority 0 in the ratified ladder, so the loader's "every signer/cosigner role must have
        // seniority >= 1" floor refuses it — platform authority may never fill a signature slot.
        var tampered = WireAdminAsCosigner(PolicyYaml());
        tampered.Should().Contain("[supervisor, admin]");

        var act = () => Load(tampered);
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>()
            .WithMessage("*banking seniority*");
    }

    [Fact]
    public void Admin_added_to_an_L1_signer_list_is_refused()
    {
        // The same escalation from the other direction: admin as an L1 signer. It must be rejected
        // both because admin is not declared in top-level signerRoles AND because it has no banking
        // seniority. Either error is sufficient; both being possible is the point.
        var tampered = PolicyYaml().Replace(
            "    signerRoles: [banker, supervisor]\n    proposable: true",
            "    signerRoles: [banker, supervisor, admin]\n    proposable: true");
        tampered.Should().Contain("[banker, supervisor, admin]");

        var act = () => Load(tampered);
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>();
    }

    // ---- Re-attack #3 (learning #2): re-encode the vulnerable ascending model ----------------

    [Fact]
    public void A_signer_role_that_restates_its_own_seniority_is_refused()
    {
        // Learning #2: a test/config that RE-ENCODES the vulnerable model — here, an inline
        // seniority under a signer role — creates a second definition that silently outvotes the
        // ratified one. The field is [YamlIgnore], so without this guard the operator would read a
        // number that is not in force. The loader re-reads the raw YAML to catch it.
        var tampered = PolicyYaml().Replace(
            "  supervisor:\n    claimValues: [supervisor, Supervisor]",
            "  supervisor:\n    seniority: 9\n    claimValues: [supervisor, Supervisor]");
        tampered.Should().Contain("seniority: 9");

        var act = () => Load(tampered);
        // Refused either by the raw-YAML re-read (RejectDeclaredSeniority) or, if the typed parser
        // is strict about unknown keys, by the parse layer — both wrap PolicyValidationException and
        // both name the offending `seniority`. What matters is that a restated seniority never loads.
        act.Should().Throw<AuthorityService.Models.PolicyValidationException>()
            .WithMessage("*seniority*");
    }

    // ---- Divergence at the hierarchy edge: the floor is only as sound as the ladder ----------

    [Fact]
    public void If_the_ratified_ladder_gives_admin_banking_seniority_the_floor_no_longer_protects()
    {
        // FINDING F3-2 (honest non-tick): the loader's "seniority >= 1" floor TRUSTS
        // role-hierarchy.yaml. It does not independently pin admin to platform-only. If a future
        // edit to role-hierarchy.yaml gave admin banking seniority >= 1, the loader would ACCEPT
        // admin in a cosigner slot and dual control would quietly collapse — exactly the Phase 1
        // shape, one file upstream. I do not assert the loader catches this (it cannot, by design:
        // it consumes the ladder, it does not ratify it). I demonstrate the exposure, then pin the
        // real ladder below so a regression there goes red.
        var wrongLadder = RoleHierarchy.LoadFromYaml(
            "version: 1\nroles:\n" +
            "  banker: { seniority: 1, implies: [] }\n" +
            "  supervisor: { seniority: 2, implies: [banker] }\n" +
            "  admin: { seniority: 3, implies: [] }\n",
            "<wrong-ladder>");

        // Fully wire admin as a signer role AND an L2 cosigner, so the seniority floor is the only
        // guard in play — exactly the tamper that the real ladder refuses in the test above.
        var tampered = WireAdminAsCosigner(PolicyYaml());

        var loader = new PolicyLoader(new Dictionary<string, string?>(), wrongLadder);
        var act = () => loader.LoadFromYaml(tampered, "<wrong-ladder-policy>");

        // The exposure: with a wrong ladder, the loader does NOT refuse admin as a cosigner. This
        // is not a pass to celebrate — it is the boundary of what this service can defend alone.
        act.Should().NotThrow(
            "documented exposure F3-2: the loader consumes seniority and cannot detect a ratified " +
            "ladder that is itself wrong; that is why the ladder is pinned by the tripwire below");
    }

    [Fact]
    public void The_ratified_ladder_keeps_admin_at_platform_zero_implying_nothing()
    {
        // The tripwire for F3-2, written in the CORRECT direction (unlike learning #2, which
        // asserted the vulnerable model). admin MUST stay at banking seniority 0 and imply neither
        // banker nor supervisor. The day someone "helpfully" makes admin a superset, this fires.
        var ladder = RatifiedHierarchy();
        ladder.Has("admin").Should().BeTrue("non-vacuity: the role must exist to be checked");
        ladder.SeniorityOf("admin").Should().Be(0,
            "admin is platform authority, not banking seniority; any positive value lets it co-sign");
        ladder.Expand(new[] { "admin" }).Should().NotContain("supervisor",
            "admin must not imply supervisor, or one identity satisfies both sides of dual control");
        ladder.Expand(new[] { "admin" }).Should().NotContain("banker",
            "admin must not imply banker, or a platform operator silently gains L1 signing");
    }
}
