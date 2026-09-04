using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace BankerCopilotTests.Spec;

public sealed record DenialValidationResult(bool Valid, string? FailedRule, string? Message)
{
    public static DenialValidationResult Ok() => new(true, null, null);
    public static DenialValidationResult Fail(string rule, string message) => new(false, rule, message);
}

public sealed record DenialReasonConfig
{
    public int MinLength { get; init; }
    public int MaxLength { get; init; }
    public int MinDistinctChars { get; init; }
    public int MaxRepeatUnit { get; init; }
    public int MinLetters { get; init; }

    /// <summary>
    /// Read from config, exactly as production does (§8.7.1: "the 20 Brian specified is the
    /// DEFAULT for DENIAL_REASON_MIN_LENGTH, not a literal in the validator"). Env overrides win,
    /// mirroring the ConfigMap path, so a test never encodes a number the config could change.
    /// </summary>
    public static DenialReasonConfig Load(string fileName = "denial-reason-config.json")
    {
        var path = Path.Combine(PolicyLoader.PolicyDirectory, fileName);
        if (!File.Exists(path))
            throw new FileNotFoundException($"Denial reason config missing at {path}.", path);

        var raw = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(File.ReadAllText(path))
                  ?? throw new InvalidOperationException("denial-reason-config.json is null.");

        int Resolve(string envKey)
        {
            var fromEnv = Environment.GetEnvironmentVariable(envKey);
            if (!string.IsNullOrWhiteSpace(fromEnv) && int.TryParse(fromEnv, out var v)) return v;
            if (!raw.TryGetValue(envKey, out var el))
                throw new InvalidOperationException($"Config key '{envKey}' is not defined.");
            return el.GetInt32();
        }

        return new DenialReasonConfig
        {
            MinLength = Resolve("DENIAL_REASON_MIN_LENGTH"),
            MaxLength = Resolve("DENIAL_REASON_MAX_LENGTH"),
            MinDistinctChars = Resolve("DENIAL_REASON_MIN_DISTINCT_CHARS"),
            MaxRepeatUnit = Resolve("DENIAL_REASON_MAX_REPEAT_UNIT"),
            MinLetters = Resolve("DENIAL_REASON_MIN_LETTERS")
        };
    }
}

/// <summary>
/// Engine §8.7.1 rules V1–V6, in order, all must pass. Every bound comes from
/// <see cref="DenialReasonConfig"/> — there is no integer literal in this class.
/// </summary>
public sealed class DenialReasonValidator(DenialReasonConfig config)
{
    public static DenialReasonValidator FromConfig() => new(DenialReasonConfig.Load());

    public DenialReasonConfig Config => config;

    public DenialValidationResult Validate(string? reason)
    {
        // V1 — present and a string.
        if (reason is null)
            return DenialValidationResult.Fail("V1", "A denial reason is required.");

        // Normalize BEFORE measuring: NFC, trim, then collapse internal whitespace runs for
        // measurement only. Otherwise "a" + 19 spaces + "b" passes a naive length check.
        var normalized = reason.Normalize(NormalizationForm.FormC).Trim();
        var measured = Regex.Replace(normalized, @"\s+", " ");

        // V2 — grapheme clusters, not bytes and not UTF-16 code units. A reason in Japanese or
        // Arabic must not need three times the substance to clear the bar.
        var graphemes = Graphemes(measured);
        if (graphemes.Count < config.MinLength)
        {
            return DenialValidationResult.Fail("V2",
                $"Your reason needs to be a bit more specific — at least {config.MinLength} characters.");
        }

        if (graphemes.Count > config.MaxLength)
            return DenialValidationResult.Fail("V6", $"Reason exceeds {config.MaxLength} characters.");

        // V3 — distinct non-whitespace characters. Kills "aaaaaaaaaaaaaaaaaaaaaa" and "......".
        var distinct = measured.Where(c => !char.IsWhiteSpace(c))
                               .Distinct()
                               .Count();
        if (distinct < config.MinDistinctChars)
        {
            return DenialValidationResult.Fail("V3",
                $"Your reason needs at least {config.MinDistinctChars} different characters.");
        }

        // V4 — the anti-mashing rule, and the one doing real work. V2+V3 alone are satisfied by
        // "asdfasdfasdfasdfasdf" (20 chars, 4 distinct).
        if (IsRepetitionOfShortUnit(measured, config.MaxRepeatUnit))
        {
            return DenialValidationResult.Fail("V4",
                "Your reason looks like repeated keystrokes rather than an explanation.");
        }

        // V5 — actual letters, not digits or punctuation padding.
        var letters = measured.Count(char.IsLetter);
        if (letters < config.MinLetters)
        {
            return DenialValidationResult.Fail("V5",
                $"Your reason needs at least {config.MinLetters} letters.");
        }

        return DenialValidationResult.Ok();
    }

    /// <summary>
    /// Is the string a whole-number repetition of some unit of length &lt;= maxUnit? Checks the
    /// raw string and the space-separated-token form, so "test test test test test" is caught as
    /// well as "asdfasdfasdf".
    /// </summary>
    private static bool IsRepetitionOfShortUnit(string s, int maxUnit)
    {
        if (s.Length == 0) return true;

        for (var unit = 1; unit <= Math.Min(maxUnit, s.Length / 2); unit++)
        {
            if (s.Length % unit != 0) continue;

            var head = s.AsSpan(0, unit);
            var repeats = true;
            for (var i = unit; i < s.Length; i += unit)
            {
                if (!s.AsSpan(i, unit).SequenceEqual(head)) { repeats = false; break; }
            }

            if (repeats) return true;
        }

        // Token-level repetition: "test test test test test".
        var tokens = s.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length >= 2 && tokens.Distinct(StringComparer.Ordinal).Count() == 1)
            return true;

        return false;
    }

    private static List<string> Graphemes(string s)
    {
        var result = new List<string>();
        var e = StringInfo.GetTextElementEnumerator(s);
        while (e.MoveNext()) result.Add((string)e.Current);
        return result;
    }
}
