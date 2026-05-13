using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Validation;

/// <summary>
/// Validates that a numeric value is not zero. Useful when paired with
/// <see cref="RangeAttribute"/> on signed-amount fields where 0 is meaningless
/// (transfers, transactions, balance adjustments).
/// </summary>
[AttributeUsage(AttributeTargets.Property | AttributeTargets.Field)]
public sealed class NotZeroAttribute : ValidationAttribute
{
    public override bool IsValid(object? value)
    {
        return value switch
        {
            null => true, // [Required] handles nulls
            decimal d => d != 0m,
            double db => db != 0d,
            float f => f != 0f,
            long l => l != 0L,
            int i => i != 0,
            short s => s != 0,
            _ => true,
        };
    }

    public override string FormatErrorMessage(string name) =>
        $"{name} must not be zero.";
}
