using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Validation;

/// <summary>
/// Validates that two properties on the same object are not equal
/// (case-insensitive for strings). Used e.g. to reject self-transfers where
/// source and destination accounts refer to the same id.
/// </summary>
[AttributeUsage(AttributeTargets.Property | AttributeTargets.Field)]
public sealed class NotEqualToAttribute : ValidationAttribute
{
    public string OtherProperty { get; }

    public NotEqualToAttribute(string otherProperty)
    {
        OtherProperty = otherProperty;
    }

    protected override ValidationResult? IsValid(object? value, ValidationContext validationContext)
    {
        var otherProp = validationContext.ObjectType.GetProperty(OtherProperty);
        if (otherProp == null)
        {
            return new ValidationResult(
                $"Unknown property '{OtherProperty}' referenced by {nameof(NotEqualToAttribute)}.");
        }

        var otherValue = otherProp.GetValue(validationContext.ObjectInstance);

        if (value is string s1 && otherValue is string s2 &&
            string.Equals(s1, s2, StringComparison.OrdinalIgnoreCase))
        {
            return new ValidationResult(
                ErrorMessage ?? $"{validationContext.DisplayName} must not equal {OtherProperty}.",
                new[] { validationContext.MemberName! });
        }

        if (value != null && otherValue != null && value is not string && value.Equals(otherValue))
        {
            return new ValidationResult(
                ErrorMessage ?? $"{validationContext.DisplayName} must not equal {OtherProperty}.",
                new[] { validationContext.MemberName! });
        }

        return ValidationResult.Success;
    }
}
