using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class CreditProfile
{
    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("bureauScore")]
    public int BureauScore { get; set; }

    [JsonProperty("scoreBand")]
    public string ScoreBand { get; set; } = string.Empty;

    [JsonProperty("delinquencies24m")]
    public int Delinquencies24m { get; set; }

    [JsonProperty("utilizationPct")]
    public double UtilizationPct { get; set; }

    [JsonProperty("hardInquiries6m")]
    public int HardInquiries6m { get; set; }

    [JsonProperty("bankruptcyFlag")]
    public string BankruptcyFlag { get; set; } = string.Empty;

    [JsonProperty("oldestTradeLineMonths")]
    public int OldestTradeLineMonths { get; set; }

    [JsonProperty("totalOpenTradelines")]
    public int TotalOpenTradelines { get; set; }

    [JsonProperty("riskTier")]
    public string RiskTier { get; set; } = string.Empty;

    [JsonProperty("delinquencies")]
    public int Delinquencies { get; set; }

    [JsonProperty("utilization")]
    public decimal Utilization { get; set; }

    [JsonProperty("accountsOpen")]
    public int AccountsOpen { get; set; }

    [JsonProperty("inquiriesLast6Mo")]
    public int InquiriesLast6Mo { get; set; }

    [JsonProperty("totalCreditLimit")]
    public decimal TotalCreditLimit { get; set; }

    [JsonProperty("averageAccountAgeMonths")]
    public int AverageAccountAgeMonths { get; set; }
}
