using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace AuthorityService.Services;

public record DenialReasonResult(bool IsValid, string? FailedRule, string? Message)
{
    public static readonly DenialReasonResult Valid = new(true, null, null);

    public static DenialReasonResult Fail(string rule, string message) => new(false, rule, message);
}

/// <summary>
/// Server-side validation of a human denial reason (epic §5.4.2, design §8.7.1).
///
/// A denial is the only moment a human tells us the agent was wrong, and denial text is the
/// only corpus of labelled agent misjudgement we will ever have — so it has to be real text.
/// The UI may mirror these rules for responsiveness; it is never the enforcement point.
///
/// <para><b>Honest limit:</b> this stops lazy input. It cannot stop determined garbage. A
/// fluent, plausible, entirely fabricated sentence passes, and no rule set will separate that
/// from a true one. Validation buys a floor, not quality.</para>
///
/// Every number below is a named config value with an env override — there are no literals.
/// </summary>
public interface IDenialReasonValidator
{
    DenialReasonResult Validate(string? reason);
}

public class DenialReasonValidator : IDenialReasonValidator
{
    private static readonly Regex WhitespaceRun = new(@"\s+", RegexOptions.Compiled);

    private readonly int _minLength;
    private readonly int _maxLength;
    private readonly int _minDistinctChars;
    private readonly int _maxRepeatUnit;
    private readonly int _minLetters;

    public DenialReasonValidator(IConfiguration configuration)
    {
        _minLength = Required(configuration, "Denial:ReasonMinLength");
        _maxLength = Required(configuration, "Denial:ReasonMaxLength");
        _minDistinctChars = Required(configuration, "Denial:ReasonMinDistinctChars");
        _maxRepeatUnit = Required(configuration, "Denial:ReasonMaxRepeatUnit");
        _minLetters = Required(configuration, "Denial:ReasonMinLetters");
    }

    private static int Required(IConfiguration configuration, string key)
    {
        var raw = configuration[key];

        if (string.IsNullOrWhiteSpace(raw) ||
            !int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
        {
            throw new InvalidOperationException(
                $"Configuration '{key}' is missing or not an integer. Denial-reason rules are " +
                "config-driven with no code-level defaults; refusing to start.");
        }

        return value;
    }

    public DenialReasonResult Validate(string? reason)
    {
        // V1 — present and a string.
        if (reason is null)
        {
            return DenialReasonResult.Fail("V1",
                "A denial reason is required. Tell us why this was wrong — it is the only record " +
                "of a human's judgement about the agent's work.");
        }

        // Normalize before measuring: NFC, trim, then collapse internal whitespace runs — for
        // MEASUREMENT ONLY. The original string is what gets stored.
        var measured = WhitespaceRun.Replace(reason.Normalize(NormalizationForm.FormC).Trim(), " ");

        // V2 — length in grapheme clusters, not bytes and not UTF-16 code units, so a reason in
        // Japanese or Arabic does not need three times the substance to clear the bar.
        var graphemes = Graphemes(measured);

        if (graphemes.Count < _minLength)
        {
            return DenialReasonResult.Fail("V2",
                $"Your reason needs to be a bit more specific — at least {_minLength} characters " +
                $"of actual content (this one has {graphemes.Count}).");
        }

        // V6 — upper bound.
        if (graphemes.Count > _maxLength)
        {
            return DenialReasonResult.Fail("V6",
                $"Your reason is longer than the {_maxLength}-character limit.");
        }

        // V3 — distinct non-whitespace characters.
        var distinct = measured.Where(c => !char.IsWhiteSpace(c)).Distinct().Count();

        if (distinct < _minDistinctChars)
        {
            return DenialReasonResult.Fail("V3",
                $"Your reason repeats too few distinct characters. It needs at least " +
                $"{_minDistinctChars} different ones.");
        }

        // V4 — the anti-mashing rule, and the one doing the real work. V2 and V3 alone are
        // satisfied by "asdfasdfasdfasdfasdf".
        if (IsRepetitionOfShortUnit(measured, _maxRepeatUnit))
        {
            return DenialReasonResult.Fail("V4",
                "Your reason looks like a repeated pattern rather than an explanation.");
        }

        // V5 — actual letters, not digits, punctuation, or emoji padding.
        var letters = measured.Count(char.IsLetter);

        if (letters < _minLetters)
        {
            return DenialReasonResult.Fail("V5",
                $"Your reason needs at least {_minLetters} letters — a few words explaining what " +
                "was wrong.");
        }

        return DenialReasonResult.Valid;
    }

    private static List<string> Graphemes(string value)
    {
        var elements = new List<string>();
        var enumerator = System.Globalization.StringInfo.GetTextElementEnumerator(value);

        while (enumerator.MoveNext())
        {
            elements.Add((string)enumerator.Current);
        }

        return elements;
    }

    /// <summary>
    /// True when the string is a whole-number repetition of some unit of length &lt;= maxUnit,
    /// where the unit may itself be a word plus a separator ("test test test test").
    /// </summary>
    private static bool IsRepetitionOfShortUnit(string value, int maxUnit)
    {
        var collapsed = value.Trim();
        if (collapsed.Length == 0) return true;

        for (var unit = 1; unit <= maxUnit && unit <= collapsed.Length / 2; unit++)
        {
            if (collapsed.Length % unit != 0) continue;

            var head = collapsed[..unit];
            var repeats = true;

            for (var offset = unit; offset < collapsed.Length; offset += unit)
            {
                if (string.CompareOrdinal(collapsed, offset, head, 0, unit) != 0)
                {
                    repeats = false;
                    break;
                }
            }

            if (repeats) return true;
        }

        // Word-level repetition: "test test test test" is one distinct word held down.
        var words = collapsed.Split(' ', StringSplitOptions.RemoveEmptyEntries);

        if (words.Length >= 3 && words.Distinct(StringComparer.OrdinalIgnoreCase).Count() == 1)
        {
            return true;
        }

        return false;
    }
}
