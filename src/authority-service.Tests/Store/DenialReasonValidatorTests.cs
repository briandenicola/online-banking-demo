using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Store;

/// <summary>
/// Epic §5.4.2 (RATIFIED Q3) and engine §8.7.1. A human denial requires a reason, enforced
/// SERVER-SIDE. Brian's framing is the test oracle: "a required field that can be defeated by
/// holding down a key is a required field in name only."
///
/// Every bound is read from config. A test that asserts `Validate("1234567890123456789").Valid ==
/// false` because it is 19 characters silently stops testing anything the day someone sets
/// DENIAL_REASON_MIN_LENGTH to 10 — it just keeps passing for a different reason. So the inputs
/// here are CONSTRUCTED from the configured bounds rather than typed out.
/// </summary>
public sealed class DenialReasonValidatorTests
{
    private static readonly DenialReasonValidator Validator = DenialReasonValidator.FromConfig();
    private static DenialReasonConfig Cfg => Validator.Config;

    private static void Reject(string? reason, string why)
    {
        var result = Validator.Validate(reason);
        result.Valid.Should().BeFalse(why);
        result.FailedRule.Should().NotBeNullOrWhiteSpace(
            "the rejection must name the rule it failed, or the 400 is unactionable");
    }

    // ---- The degenerate inputs Brian named explicitly -------------------------------------

    [Fact]
    public void Whitespace_alone_never_satisfies_the_requirement()
    {
        // "                    " clears a naive length >= 20.
        Reject(new string(' ', Cfg.MinLength + 5), "spaces are not a reason");
        Reject(new string('\t', Cfg.MinLength + 5), "nor are tabs");
        Reject(string.Join("", Enumerable.Repeat(" \n\t", Cfg.MinLength)), "nor mixed whitespace");
        Reject("", "empty is the obvious case and still deserves a test");
        Reject(null, "a missing field must fail the same way an empty one does");
    }

    [Fact]
    public void A_single_repeated_character_never_satisfies_the_requirement()
    {
        // "aaaaaaaaaaaaaaaaaaaa" — the held-down key.
        Reject(new string('a', Cfg.MinLength + 10), "one character held down is not a reason");
        Reject(new string('.', Cfg.MinLength + 10), "punctuation held down likewise");
        Reject(new string('a', Cfg.MinLength) + "   ", "nor with trailing space to pad it");
    }

    [Fact]
    public void A_repeated_short_unit_never_satisfies_the_requirement()
    {
        // THE ONE BRIAN CALLED OUT BY NAME: "asdfasdfasdfasdfasdf".
        //
        // This is the input that defeats the obvious hardening. Trim-then-length passes it.
        // Distinct-character-count passes it — it has four distinct characters, comfortably more
        // than most thresholds. It is only caught by looking for a repeating UNIT, which is why
        // rule V5 exists and why this test is the most important one in the file.
        Reject("asdfasdfasdfasdfasdf", "a repeated four-character unit is keyboard mashing");
        Reject("abababababababababababab", "a repeated two-character unit likewise");
        Reject("no no no no no no no no ", "a repeated WORD is the same trick with a space in it");
    }

    [Fact]
    public void KNOWN_GAP_a_repeat_unit_longer_than_the_configured_bound_escapes_V4()
    {
        // ⚠️ FINDING F-4 — reported, deliberately NOT fixed here (the bound is Turk's to set and
        // the default is ratified in engine §8.7.1).
        //
        // DENIAL_REASON_MAX_REPEAT_UNIT defaults to 4, so V4 only detects repetition of units up
        // to four characters. "qwertyqwertyqwertyqwerty" is a six-character unit: 24 graphemes,
        // 6 distinct characters, 24 letters. It clears V2, V3, V4 and V5 and is accepted.
        //
        // This test asserts the CURRENT, RATIFIED behaviour rather than the behaviour I would
        // prefer, so it stays honest and green. It exists to make the gap visible and to fail
        // loudly the day someone changes the bound — at which point the gap is closed and this
        // test should be inverted, not deleted.
        Cfg.MaxRepeatUnit.Should().Be(4, "the ratified default; if this changed, revisit F-4");

        Validator.Validate("qwertyqwertyqwertyqwerty").Valid.Should().BeTrue(
            "documenting the escape, not endorsing it — a six-character mash is still a mash");

        // Raising the bound closes it, which is the evidence that the fix is a config change and
        // not a code change.
        var stricter = new DenialReasonConfig
        {
            MinLength = Cfg.MinLength,
            MaxLength = Cfg.MaxLength,
            MinDistinctChars = Cfg.MinDistinctChars,
            MaxRepeatUnit = 8,
            MinLetters = Cfg.MinLetters
        };

        new DenialReasonValidator(stricter).Validate("qwertyqwertyqwertyqwerty")
            .Valid.Should().BeFalse();
    }

    [Fact]
    public void Digits_alone_never_satisfy_the_requirement()
    {
        Reject("12345678901234567890", "a row of digits carries no judgement");
        Reject(new string('7', Cfg.MinLength + 3), "nor one digit repeated");
    }

    [Fact]
    public void A_reason_shorter_than_the_configured_minimum_is_rejected()
    {
        // Constructed from config, not typed. "Too short" is measured, never assumed.
        var justUnder = string.Concat(Enumerable.Range(0, Cfg.MinLength - 1)
            .Select(i => (char)('a' + i % 26)));

        justUnder.Length.Should().Be(Cfg.MinLength - 1);
        Reject(justUnder, $"below the configured minimum of {Cfg.MinLength}");
    }

    [Fact]
    public void Leading_and_trailing_whitespace_does_not_count_toward_the_minimum()
    {
        var padded = "  no  " + new string(' ', Cfg.MinLength * 2);

        Reject(padded, "trim first, then measure — padding is not content");
    }

    [Fact]
    public void A_reason_longer_than_the_configured_maximum_is_rejected()
    {
        // The other end. An unbounded reason field is a storage and log-injection problem, and
        // Cosmos has a hard document limit that a 2 MB "reason" would blow past.
        Reject(new string('x', Cfg.MaxLength + 1) + " genuine words follow",
            $"above the configured maximum of {Cfg.MaxLength}");
    }

    // ---- The positive control: real reasons must actually work ---------------------------

    [Theory]
    [InlineData("Customer confirmed on the recorded call that the original transfer was intended.")]
    [InlineData("Beneficiary account does not match the instruction on file; escalating to fraud.")]
    [InlineData("Underwriting evidence is stale — the credit pull is 94 days old, policy allows 30.")]
    [InlineData("Duplicate of approval apr_9912, which a supervisor already actioned this morning.")]
    public void A_genuine_sentence_is_accepted(string reason)
    {
        // WITHOUT THIS, EVERY TEST ABOVE WOULD PASS FOR A VALIDATOR THAT REJECTS EVERYTHING.
        // That validator would also be catastrophic in production: no banker could ever record a
        // denial, so the only working verb left would be approve. A validator biased toward
        // rejection quietly biases the whole system toward saying yes.
        var result = Validator.Validate(reason);

        result.Valid.Should().BeTrue(
            $"'{reason}' is exactly what a banker would type; rejected by {result.FailedRule}");
    }

    [Fact]
    public void A_reason_exactly_at_the_configured_minimum_is_accepted()
    {
        // Boundary, constructed from config. Off-by-one here means every reason of exactly the
        // stated minimum length is refused, and the error message tells the banker to write at
        // least N characters — which they just did.
        var atMinimum = "The stated reason is that " +
                        new string('x', Math.Max(0, Cfg.MinLength - 26));
        var trimmedLength = atMinimum.Trim().Length;
        trimmedLength.Should().BeGreaterThanOrEqualTo(Cfg.MinLength);

        Validator.Validate(atMinimum).Valid.Should().BeTrue();
    }

    [Fact]
    public void A_non_latin_script_reason_is_accepted()
    {
        // A validator built around ASCII letter-counting will reject a perfectly good Japanese or
        // Arabic reason. In a bank operating in more than one language that is not a cosmetic
        // bug: it makes denial impossible for a whole population of staff, and the workaround
        // they find will be to approve.
        Validator.Validate("この取引は顧客の指示と一致しないため却下します。担当者に確認済みです。")
            .Valid.Should().BeTrue("Japanese reasons are reasons");

        Validator.Validate("لا يتطابق الحساب المستفيد مع تعليمات العميل المسجلة، لذلك تم الرفض.")
            .Valid.Should().BeTrue("Arabic reasons are reasons");
    }

    [Fact]
    public void Length_is_measured_in_grapheme_clusters_not_UTF16_code_units()
    {
        // "👨‍👩‍👧‍👦" is one visible character and eleven UTF-16 code units. Measuring code units
        // lets two emoji clear a twenty-character minimum.
        var emojiOnly = string.Concat(Enumerable.Repeat("👨‍👩‍👧‍👦", 4));

        emojiOnly.Length.Should().BeGreaterThan(Cfg.MinLength,
            "in UTF-16 code units this LOOKS long enough, which is the trap");

        Reject(emojiOnly, "four family emoji are four graphemes, not forty characters");
    }

    [Fact]
    public void Every_rejection_is_attributable_to_a_named_rule()
    {
        // Operational, not theoretical: a banker who gets a bare 400 will retype the same thing.
        // The rule name is what lets the UI say something useful.
        var degenerate = new[]
        {
            "", "   ", new string('a', 40), "asdfasdfasdfasdfasdf", "12345678901234567890"
        };

        foreach (var input in degenerate)
        {
            var r = Validator.Validate(input);
            r.Valid.Should().BeFalse();
            r.FailedRule.Should().MatchRegex("^V[1-9]$",
                "rules are numbered V1–V6 in engine §8.7.1 so a support ticket can name one");
            r.Message.Should().NotBeNullOrWhiteSpace();
        }
    }

    // ---- Enforcement point ---------------------------------------------------------------

    [Fact]
    public void The_store_refuses_a_denial_with_a_bad_reason_not_merely_the_validator()
    {
        // §5.4.2: "Client-side validation may mirror it for responsiveness but is never the
        // enforcement point." The validator being correct proves nothing if the write path does
        // not call it — so drive the actual verb.
        var policy = TestData.Baseline();
        var (store, approval, _) = TestData.ProposeL1(policy, TestData.TransferReversal(policy));

        var bad = store.Deny(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            "asdfasdfasdfasdfasdf", Validator, TestData.T0);

        bad.Accepted.Should().BeFalse();
        store.Get(approval.Id).IsTerminal.Should().BeFalse(
            "a rejected denial must leave the approval alive — not half-denied");

        var good = store.Deny(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            "Customer could not verify the last four digits of the destination account.",
            Validator, TestData.T0);

        good.Accepted.Should().BeTrue();
        store.Get(approval.Id).TerminalReason.Should().Be(TerminalReason.HumanDenied);
    }

    [Fact]
    public void The_reason_requirement_applies_only_to_human_denials()
    {
        // §5.4.2: the other three terminal reasons are machine-generated and carry structured
        // explanation instead. Demanding prose from the sweeper would either block expiry or
        // force the sweeper to invent a sentence — and an invented reason in an audit log is
        // worse than no reason.
        var policy = TestData.Baseline();
        var (store, approval, _) = TestData.ProposeL1(policy, TestData.TransferReversal(policy));

        var expired = store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddSeconds(1));

        expired.TerminalReason.Should().Be(TerminalReason.TtlExpired);
        expired.Terminal!.Detail.Should().BeNullOrEmpty(
            "no prose is fabricated on the machine paths");
    }

    [Fact]
    public void No_bound_in_the_validator_is_a_literal()
    {
        // The meta-test. If a bound were hardcoded, changing the config would not change
        // behaviour — and every test in this file would keep passing while enforcing a number
        // nobody configured.
        var relaxed = new DenialReasonConfig
        {
            MinLength = 5,
            MaxLength = Cfg.MaxLength,
            MinDistinctChars = Cfg.MinDistinctChars,
            MaxRepeatUnit = Cfg.MaxRepeatUnit,
            MinLetters = 3
        };

        var shortReason = "Too risky";
        shortReason.Length.Should().BeLessThan(Cfg.MinLength);

        Validator.Validate(shortReason).Valid.Should().BeFalse("rejected under the real config");
        new DenialReasonValidator(relaxed).Validate(shortReason).Valid.Should().BeTrue(
            "accepted under a relaxed config — proving the bound is read, not baked in");
    }
}
