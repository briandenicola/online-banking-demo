using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class IncomeVerification
{
    [JsonProperty("verifiedMonthlyIncome")]
    public decimal VerifiedMonthlyIncome { get; set; }

    [JsonProperty("employmentStatus")]
    public string EmploymentStatus { get; set; } = string.Empty;

    [JsonProperty("employerName")]
    public string EmployerName { get; set; } = string.Empty;

    [JsonProperty("tenureMonths")]
    public int TenureMonths { get; set; }

    [JsonProperty("incomeStability")]
    public string IncomeStability { get; set; } = string.Empty;

    [JsonProperty("additionalIncomeVerified")]
    public decimal AdditionalIncomeVerified { get; set; }
}
