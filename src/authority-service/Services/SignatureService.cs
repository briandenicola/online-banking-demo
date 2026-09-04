using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace AuthorityService.Services;

public record SigningInput(
    string ApprovalId,
    string ActionId,
    string PolicyVersion,
    string PayloadHash,
    string SignerUserId,
    string SignerTokenJti,
    int SlotOrdinal,
    DateTime SignedAtUtc,
    string Nonce);

public interface ISignatureService
{
    string Sign(SigningInput input);
    bool Verify(SigningInput input, string signature);
}

/// <summary>
/// Produces the server-side signature that binds a human action to an exact payload
/// (design §6.3).
///
/// <code>
/// "bcp-sig.v2" \n approvalId \n actionId \n policyVersion \n payloadHash \n
/// signerUserId \n signerTokenJti \n slotOrdinal \n signedAtRfc3339 \n nonce
/// </code>
///
/// <para><b>slotOrdinal is load-bearing:</b> without it a captured signature could be replayed
/// into the second slot, defeating dual control even though the identities differ.</para>
///
/// <para>This is not a client-side crypto scheme. The security claim is "the service observed a
/// fresh, authenticated human action and bound it immutably to this exact payload" — not "the
/// human personally wielded a private key".</para>
/// </summary>
public class HmacSignatureService : ISignatureService
{
    private readonly byte[] _key;

    public HmacSignatureService(IConfiguration configuration)
    {
        var key = configuration["Approval:SigningKey"];

        if (string.IsNullOrWhiteSpace(key))
        {
            throw new InvalidOperationException(
                "Approval__SigningKey is not configured. It must be distinct from every other " +
                "credential this service holds, so that compromising one does not yield the " +
                "ability to forge approval signatures. Refusing to start.");
        }

        // The old comparison was against Jwt__Key, the shared symmetric signing secret. That
        // setting is retired (issue #334) and its presence now aborts startup, so the check
        // could never fire again. The credentials this service actually holds today are the
        // mediator client secret and — if an operator misconfigures it — JWT signing material.
        // Reusing either as the approval key would collapse two independent controls into one.
        var neighbours = new (string Name, string? Value)[]
        {
            ("Jwt__MediatorClientSecret", configuration["Jwt:MediatorClientSecret"]),
            ("Jwt__PrivateKeyPem", configuration["Jwt:PrivateKeyPem"])
        };

        foreach (var (name, value) in neighbours)
        {
            if (!string.IsNullOrWhiteSpace(value) && string.Equals(key, value, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    $"Approval__SigningKey must not equal {name}. Key separation is the whole " +
                    "control: one credential serving two purposes means one leak defeats both.");
            }
        }

        _key = Encoding.UTF8.GetBytes(key);
    }

    public string Sign(SigningInput input)
    {
        var preimage = Preimage(input);
        var mac = HMACSHA256.HashData(_key, Encoding.UTF8.GetBytes(preimage));

        return "hmac-sha256:" + Convert.ToHexString(mac).ToLowerInvariant();
    }

    public bool Verify(SigningInput input, string signature)
    {
        var expected = Sign(input);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(expected),
            Encoding.UTF8.GetBytes(signature));
    }

    internal static string Preimage(SigningInput input) => new StringBuilder()
        .Append(SharedIdentifiers.SignatureScheme).Append('\n')
        .Append(input.ApprovalId).Append('\n')
        .Append(input.ActionId).Append('\n')
        .Append(input.PolicyVersion).Append('\n')
        .Append(input.PayloadHash).Append('\n')
        .Append(input.SignerUserId).Append('\n')
        .Append(input.SignerTokenJti).Append('\n')
        .Append(input.SlotOrdinal.ToString(CultureInfo.InvariantCulture)).Append('\n')
        .Append(input.SignedAtUtc.ToString("o", CultureInfo.InvariantCulture)).Append('\n')
        .Append(input.Nonce)
        .ToString();
}
