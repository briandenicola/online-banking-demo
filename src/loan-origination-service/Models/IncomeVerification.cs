using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class IncomeVerification
{
    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("verifiedMonthlyIncome")]
    public decimal VerifiedMonthlyIncome { get; set; }

    [JsonProperty("verificationStatus")]
    public string VerificationStatus { get; set; } = string.Empty;

    [JsonProperty("payrollRecordsMonths")]
    public int PayrollRecordsMonths { get; set; }

    [JsonProperty("incomeVariancePct")]
    public decimal IncomeVariancePct { get; set; }

    [JsonProperty("employerMatchPct")]
    public decimal EmployerMatchPct { get; set; }

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
