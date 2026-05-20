using System.ComponentModel.DataAnnotations;
using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class LoanApplication
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("userId")]
    [Required]
    public string UserId { get; set; } = string.Empty;

    [JsonProperty("applicationDate")]
    public DateTime ApplicationDate { get; set; }

    [JsonProperty("status")]
    public string Status { get; set; } = "submitted";

    [JsonProperty("applicant")]
    [Required]
    public ApplicantInfo Applicant { get; set; } = new();

    [JsonProperty("loanRequest")]
    [Required]
    public LoanRequestInfo LoanRequest { get; set; } = new();

    [JsonProperty("financials")]
    [Required]
    public FinancialInfo Financials { get; set; } = new();

    [JsonProperty("lastRunId")]
    public string? LastRunId { get; set; }

    [JsonProperty("lastDecisionId")]
    public string? LastDecisionId { get; set; }

    [JsonProperty("fundedLoanAccountId")]
    public string? FundedLoanAccountId { get; set; }

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; }

    [JsonProperty("updatedAt")]
    public DateTime UpdatedAt { get; set; }

    [JsonProperty("_etag")]
    public string? ETag { get; set; }
}

public class ApplicantInfo
{
    [JsonProperty("name")]
    [Required]
    public string Name { get; set; } = string.Empty;

    [JsonProperty("dob")]
    [Required]
    public string Dob { get; set; } = string.Empty;

    [JsonProperty("ssnLast4")]
    [Required]
    [StringLength(4, MinimumLength = 4)]
    public string SsnLast4 { get; set; } = string.Empty;

    [JsonProperty("phone")]
    public string Phone { get; set; } = string.Empty;

    [JsonProperty("email")]
    [Required]
    [EmailAddress]
    public string Email { get; set; } = string.Empty;

    [JsonProperty("currentAddress")]
    public string CurrentAddress { get; set; } = string.Empty;

    [JsonProperty("cityStateZip")]
    public string CityStateZip { get; set; } = string.Empty;
}

public class LoanRequestInfo
{
    [JsonProperty("amount")]
    [Required]
    [Range(1000, 500000)]
    public decimal Amount { get; set; }

    [JsonProperty("purpose")]
    [Required]
    public string Purpose { get; set; } = string.Empty;

    [JsonProperty("termMonths")]
    [Required]
    public int TermMonths { get; set; }

    [JsonProperty("loanType")]
    [Required]
    public string LoanType { get; set; } = string.Empty;

    [JsonProperty("paymentMethod")]
    public string PaymentMethod { get; set; } = "AUTO_DEBIT";
}

public class FinancialInfo
{
    [JsonProperty("grossAnnualIncome")]
    [Required]
    public decimal GrossAnnualIncome { get; set; }

    [JsonProperty("monthlyNetIncome")]
    [Required]
    public decimal MonthlyNetIncome { get; set; }

    [JsonProperty("otherIncomeMonthly")]
    public decimal OtherIncomeMonthly { get; set; }

    [JsonProperty("totalMonthlyDebtPayments")]
    public decimal TotalMonthlyDebtPayments { get; set; }

    [JsonProperty("housingStatus")]
    public string HousingStatus { get; set; } = "rent";

    [JsonProperty("housingPaymentMonthly")]
    public decimal HousingPaymentMonthly { get; set; }

    [JsonProperty("declaredDtiPct")]
    public decimal DeclaredDtiPct { get; set; }

    [JsonProperty("estimatedSavings")]
    public decimal EstimatedSavings { get; set; }

    [JsonProperty("retirementInvestments")]
    public decimal RetirementInvestments { get; set; }
}
