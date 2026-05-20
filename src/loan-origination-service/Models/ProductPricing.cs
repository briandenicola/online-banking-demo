using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class ProductPricing
{
    [JsonProperty("pricingRuleId")]
    public string PricingRuleId { get; set; } = string.Empty;

    [JsonProperty("riskTier")]
    public string RiskTier { get; set; } = string.Empty;

    [JsonProperty("loanType")]
    public string LoanType { get; set; } = string.Empty;

    [JsonProperty("termMonths")]
    public int TermMonths { get; set; }

    [JsonProperty("minAmount")]
    public decimal MinAmount { get; set; }

    [JsonProperty("maxAmount")]
    public decimal MaxAmount { get; set; }

    [JsonProperty("minCreditScore")]
    public int MinCreditScore { get; set; }

    [JsonProperty("maxDtiPct")]
    public decimal MaxDtiPct { get; set; }

    [JsonProperty("aprPct")]
    public decimal AprPct { get; set; }

    [JsonProperty("monthlyPayment")]
    public decimal MonthlyPayment { get; set; }

    [JsonProperty("totalRepayableAmount")]
    public decimal TotalRepayableAmount { get; set; }

    [JsonProperty("originationFeePct")]
    public decimal OriginationFeePct { get; set; }

    [JsonProperty("firstPaymentDate")]
    public string FirstPaymentDate { get; set; } = string.Empty;

    [JsonProperty("payoffDate")]
    public string PayoffDate { get; set; } = string.Empty;
}

public class PolicyThreshold
{
    [JsonProperty("riskTier")]
    public string RiskTier { get; set; } = string.Empty;

    [JsonProperty("minAprPct")]
    public decimal MinAprPct { get; set; }

    [JsonProperty("maxAprPct")]
    public decimal MaxAprPct { get; set; }

    [JsonProperty("baseAprPct")]
    public decimal BaseAprPct { get; set; }
}
