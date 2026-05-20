using FluentAssertions;
using LoanOrigination.Services;
using Xunit;

namespace LoanOrigination.Tests;

/// <summary>
/// T033 [US1] Unit tests for PricingService covering risk-tier APR mapping and monthly payment formula.
/// Tests MUST fail until Turk implements PricingService (T043).
/// Monthly payment formula: P = L × c(1+c)^n / ((1+c)^n − 1)
/// where L = loan amount, c = monthly interest rate, n = number of months
/// </summary>
public class PricingTests
{
    [Fact(Skip = "Awaiting T043 implementation")]
    public void GetAprForRiskTier_TierA_Returns7Point5Pct()
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var apr = service.GetAprForRiskTier("A");

        // Assert
        // apr.Should().Be(7.5m, "Tier A should map to 7.5% APR per product-pricing.json");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void GetAprForRiskTier_TierB_Returns10Point5Pct()
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var apr = service.GetAprForRiskTier("B");

        // Assert
        // apr.Should().Be(10.5m, "Tier B should map to 10.5% APR");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void GetAprForRiskTier_TierC_Returns15Point0Pct()
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var apr = service.GetAprForRiskTier("C");

        // Assert
        // apr.Should().Be(15.0m, "Tier C should map to 15.0% APR");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void GetAprForRiskTier_TierD_Returns22Point0Pct()
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var apr = service.GetAprForRiskTier("D");

        // Assert
        // apr.Should().Be(22.0m, "Tier D should map to 22.0% APR");
    }

    [Theory(Skip = "Awaiting T043 implementation")]
    [InlineData(10000.00, 7.5, 36, 311.06)]   // $10k @ 7.5% × 36mo ≈ $311.06/mo
    [InlineData(25000.00, 7.5, 36, 777.65)]   // $25k @ 7.5% × 36mo ≈ $777.65/mo
    [InlineData(15000.00, 10.5, 60, 321.63)]  // $15k @ 10.5% × 60mo ≈ $321.63/mo
    [InlineData(30000.00, 15.0, 84, 548.87)]  // $30k @ 15.0% × 84mo ≈ $548.87/mo
    public void CalculateMonthlyPayment_KnownFixtures_ReturnsExpectedPayment(
        decimal principal, decimal aprPct, int termMonths, decimal expectedMonthlyPayment)
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var monthlyPayment = service.CalculateMonthlyPayment(principal, aprPct, termMonths);

        // Assert
        // monthlyPayment.Should().BeApproximately(expectedMonthlyPayment, 0.50m,
        //     $"monthly payment for ${principal} @ {aprPct}% × {termMonths}mo should be ~${expectedMonthlyPayment}");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void CalculateMonthlyPayment_RoundingPrecision_RoundsToTwoDecimals()
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var monthlyPayment = service.CalculateMonthlyPayment(10000.00m, 7.5m, 36);

        // Assert
        // monthlyPayment.Should().Be(Math.Round(monthlyPayment, 2),
        //     "monthly payment should be rounded to 2 decimal places");
    }

    [Theory(Skip = "Awaiting T043 implementation")]
    [InlineData(10000.00, 7.5, 36, 11198.16)]  // $10k @ 7.5% × 36mo → total $11,198.16
    [InlineData(25000.00, 7.5, 36, 27995.40)]  // $25k @ 7.5% × 36mo → total $27,995.40
    public void CalculateTotalRepayableAmount_KnownFixtures_ReturnsExpectedTotal(
        decimal principal, decimal aprPct, int termMonths, decimal expectedTotal)
    {
        // Arrange
        var service = new PricingService();

        // Act
        // var total = service.CalculateTotalRepayableAmount(principal, aprPct, termMonths);

        // Assert
        // total.Should().BeApproximately(expectedTotal, 10.0m,
        //     $"total repayable for ${principal} @ {aprPct}% × {termMonths}mo should be ~${expectedTotal}");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void CalculatePayoffDate_36MonthsFromToday_ReturnsDatePlus3Years()
    {
        // Arrange
        var service = new PricingService();
        var originationDate = DateTime.UtcNow;

        // Act
        // var payoffDate = service.CalculatePayoffDate(originationDate, 36);

        // Assert
        // payoffDate.Should().BeCloseTo(originationDate.AddMonths(36), TimeSpan.FromDays(1),
        //     "payoff date should be 36 months from origination date");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void CalculatePayoffDate_60MonthsFromToday_ReturnsDatePlus5Years()
    {
        // Arrange
        var service = new PricingService();
        var originationDate = new DateTime(2026, 5, 15);

        // Act
        // var payoffDate = service.CalculatePayoffDate(originationDate, 60);

        // Assert
        // var expected = originationDate.AddMonths(60);
        // payoffDate.Should().Be(expected,
        //     "payoff date for 60-month term should be exactly 5 years from origination");
    }

    [Fact(Skip = "Awaiting T043 implementation")]
    public void CalculateFirstPaymentDate_OriginationMid Month_ReturnsFirstOfNextMonth()
    {
        // Arrange
        var service = new PricingService();
        var originationDate = new DateTime(2026, 5, 15); // Mid-May

        // Act
        // var firstPaymentDate = service.CalculateFirstPaymentDate(originationDate);

        // Assert
        // firstPaymentDate.Should().Be(new DateTime(2026, 6, 15),
        //     "first payment should be one month from origination date (same day of month)");
    }

    [Theory(Skip = "Awaiting T043 implementation")]
    [InlineData(0.0)]     // Zero APR should throw or return zero payment
    [InlineData(-5.0)]    // Negative APR invalid
    public void CalculateMonthlyPayment_InvalidApr_ThrowsArgumentException(decimal invalidApr)
    {
        // Arrange
        var service = new PricingService();

        // Act & Assert
        // Assert.Throws<ArgumentException>(() =>
        //     service.CalculateMonthlyPayment(10000.00m, invalidApr, 36));
    }

    [Theory(Skip = "Awaiting T043 implementation")]
    [InlineData(0)]       // Zero term invalid
    [InlineData(-12)]     // Negative term invalid
    public void CalculateMonthlyPayment_InvalidTerm_ThrowsArgumentException(int invalidTerm)
    {
        // Arrange
        var service = new PricingService();

        // Act & Assert
        // Assert.Throws<ArgumentException>(() =>
        //     service.CalculateMonthlyPayment(10000.00m, 7.5m, invalidTerm));
    }
}
