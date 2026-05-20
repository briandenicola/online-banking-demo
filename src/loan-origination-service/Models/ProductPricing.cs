using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class ProductPricing
{
    [JsonProperty("riskTier")]
    public string RiskTier { get; set; } = string.Empty;

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
