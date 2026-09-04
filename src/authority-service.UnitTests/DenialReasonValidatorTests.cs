using AuthorityService.Services;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

public class DenialReasonValidatorTests
{
    private static readonly DenialReasonValidator Validator = new(TestHarness.Configuration());

    [Fact]
    public void A_real_explanation_is_accepted()
    {
        Validator.Validate(
                "The customer confirmed this charge in branch, so the reversal is not warranted.")
            .IsValid.Should().BeTrue();
    }

    [Fact]
    public void A_missing_reason_is_rejected()
    {
        var result = Validator.Validate(null);

        result.IsValid.Should().BeFalse();
        result.FailedRule.Should().Be("V1");
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("no")]
    [InlineData("wrong")]
    [InlineData("not right at all")]
    public void A_reason_shorter_than_the_configured_minimum_is_rejected(string reason)
    {
        Validator.Validate(reason).IsValid.Should().BeFalse();
    }

    [Fact]
    public void Padding_with_whitespace_does_not_buy_length()
    {
        // Whitespace runs are collapsed FOR MEASUREMENT, so "no" + 40 spaces is still "no".
        Validator.Validate("no" + new string(' ', 60) + "way").IsValid.Should().BeFalse();
    }

    [Fact]
    public void A_single_repeated_character_is_rejected()
    {
        var result = Validator.Validate(new string('x', 40));

        result.IsValid.Should().BeFalse();
        result.FailedRule.Should().Be("V3");
    }

    [Fact]
    public void A_repeated_short_unit_is_rejected()
    {
        // The rule that does the real work: V2 and V3 alone are both satisfied by this.
        var result = Validator.Validate(string.Concat(Enumerable.Repeat("abcdefgh", 6)));

        result.IsValid.Should().BeFalse();
        result.FailedRule.Should().Be("V4");
    }

    [Fact]
    public void Digits_and_punctuation_alone_do_not_count_as_an_explanation()
    {
        var result = Validator.Validate("1234567890 !@#$%^&*() 1234567890 !@#$%^&*()");

        result.IsValid.Should().BeFalse();
        result.FailedRule.Should().Be("V5");
    }

    [Fact]
    public void An_over_long_reason_is_rejected()
    {
        var result = Validator.Validate(string.Concat(Enumerable.Repeat("The customer disputed. ", 200)));

        result.IsValid.Should().BeFalse();
        result.FailedRule.Should().Be("V6");
    }

    [Fact]
    public void Non_latin_text_is_measured_in_grapheme_clusters_not_bytes()
    {
        // A reason in Japanese should not need three times the substance to clear the bar.
        Validator.Validate("この取引は顧客が支店で確認済みのため、取り消す必要はありません。")
            .IsValid.Should().BeTrue();
    }

    [Fact]
    public void The_thresholds_come_from_configuration_not_from_code()
    {
        var strict = new DenialReasonValidator(TestHarness.Configuration(("Denial:ReasonMinLength", "200")));

        strict.Validate("The customer confirmed this charge in branch, so no reversal is needed.")
            .IsValid.Should().BeFalse();
    }

    [Fact]
    public void A_validator_with_no_configured_thresholds_refuses_to_start()
    {
        var empty = new Microsoft.Extensions.Configuration.ConfigurationBuilder().Build();

        var act = () => new DenialReasonValidator(empty);

        act.Should().Throw<InvalidOperationException>();
    }
}
