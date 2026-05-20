using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class FraudSignals
{
    [JsonProperty("identityRiskScore")]
    public decimal IdentityRiskScore { get; set; }

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
