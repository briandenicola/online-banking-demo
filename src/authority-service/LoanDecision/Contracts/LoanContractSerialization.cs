using Newtonsoft.Json;
using Newtonsoft.Json.Converters;

namespace AuthorityService.LoanDecision.Contracts;

public sealed class ClosedStringEnumConverter : StringEnumConverter
{
    public ClosedStringEnumConverter()
    {
        AllowIntegerValues = false;
    }
}

public static class LoanContractSerialization
{
    public static readonly JsonSerializerSettings Settings = new()
    {
        MissingMemberHandling = MissingMemberHandling.Error,
        NullValueHandling = NullValueHandling.Include,
        DateParseHandling = DateParseHandling.DateTimeOffset,
        DateTimeZoneHandling = DateTimeZoneHandling.Utc,
        Formatting = Formatting.None
    };

    public static string Serialize(object value) =>
        JsonConvert.SerializeObject(value, Settings);

    public static T Deserialize<T>(string json) =>
        JsonConvert.DeserializeObject<T>(json, Settings)
        ?? throw new JsonSerializationException($"Loan contract {typeof(T).Name} was null.");
}
