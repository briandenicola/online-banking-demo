using System.Text;
using Microsoft.Azure.Cosmos;
using Newtonsoft.Json;

namespace AuthorityService.Models;

/// <summary>
/// The one serializer configuration for approval documents, stated explicitly rather than
/// inherited.
///
/// Design §5.3.1b: Cosmos SQL field paths are case-sensitive and a mismatch returns <b>zero rows
/// rather than an error</b>. In a service that gates money movement, "the supervisor's inbox is
/// empty" and "the query is broken" must never be indistinguishable — so nothing about the wire
/// shape is left to a default that a library upgrade could change underneath us.
///
/// Two choices are load-bearing:
/// <list type="bullet">
/// <item><b>No naming policy.</b> Every property carries an explicit <c>[JsonProperty]</c>. A
/// contract resolver that camel-cases whatever it is given would silently rename any property
/// that ever loses its attribute; here that omission fails the schema test instead.</item>
/// <item><b>Nulls are written, not omitted.</b> An absent <c>terminalReason</c> and a null one
/// are different things to a Cosmos query, and the §5.3.1b path-set equality check cannot see a
/// field that was dropped for being null.</item>
/// </list>
/// </summary>
public static class ApprovalSerialization
{
    public static readonly JsonSerializerSettings Settings = new()
    {
        NullValueHandling = NullValueHandling.Include,
        DateParseHandling = DateParseHandling.DateTimeOffset,
        DateTimeZoneHandling = DateTimeZoneHandling.Utc,
        Formatting = Formatting.None
    };

    public static string Serialize(object value) => JsonConvert.SerializeObject(value, Settings);

    public static T? Deserialize<T>(string json) => JsonConvert.DeserializeObject<T>(json, Settings);
}

/// <summary>
/// Cosmos serializer bound to <see cref="ApprovalSerialization.Settings"/>, so the document the
/// SDK writes is byte-for-byte the document the schema test asserts.
/// </summary>
public class ApprovalCosmosSerializer : CosmosSerializer
{
    private static readonly JsonSerializer Serializer =
        JsonSerializer.Create(ApprovalSerialization.Settings);

    public override T FromStream<T>(Stream stream)
    {
        using (stream)
        {
            if (typeof(Stream).IsAssignableFrom(typeof(T)))
            {
                return (T)(object)stream;
            }

            using var reader = new StreamReader(stream);
            using var jsonReader = new JsonTextReader(reader);

            return Serializer.Deserialize<T>(jsonReader)!;
        }
    }

    public override Stream ToStream<T>(T input)
    {
        var payload = new MemoryStream();
        using (var writer = new StreamWriter(payload, new UTF8Encoding(false, true), 1024, leaveOpen: true))
        using (var jsonWriter = new JsonTextWriter(writer))
        {
            Serializer.Serialize(jsonWriter, input);
            jsonWriter.Flush();
        }

        payload.Position = 0;

        return payload;
    }
}
