using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class FraudSignals
{
    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("identityRiskScore")]
    public decimal IdentityRiskScore { get; set; }

    [JsonProperty("deviceRiskScore")]
    public decimal DeviceRiskScore { get; set; }

    [JsonProperty("addressMismatchFlag")]
    public string AddressMismatchFlag { get; set; } = string.Empty;

    [JsonProperty("syntheticIdFlag")]
    public string SyntheticIdFlag { get; set; } = string.Empty;

    [JsonProperty("watchlistHitFlag")]
    public string WatchlistHitFlag { get; set; } = string.Empty;

    [JsonProperty("recommendedManualReview")]
    public string RecommendedManualReview { get; set; } = string.Empty;

    [JsonProperty("addressVerified")]
    public bool AddressVerified { get; set; }

    [JsonProperty("phoneVerified")]
    public bool PhoneVerified { get; set; }

    [JsonProperty("emailVerified")]
    public bool EmailVerified { get; set; }

    [JsonProperty("ssnVerified")]
    public bool SsnVerified { get; set; }

    [JsonProperty("deviceFingerprintRisk")]
    public string DeviceFingerprintRisk { get; set; } = string.Empty;

    [JsonProperty("behavioralFlags")]
    public List<string> BehavioralFlags { get; set; } = new();
}
