using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class CreditProfile
{
    [JsonProperty("bureauScore")]
    public int BureauScore { get; set; }

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
