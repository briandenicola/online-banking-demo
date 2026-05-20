using LoanOrigination.Models;
using LoanOrigination.Repositories;

namespace LoanOrigination.Services;

/// <summary>
/// Evaluates POL-001 through POL-010 policy rules against enriched application data.
/// Returns per-rule hits with severity (hard/soft) and decision effect (DECLINE/CONDITIONAL/PASS).
/// </summary>
public class PolicyEvaluationService
{
    private readonly CosmosPolicyRepository _policyRepo;
    private readonly ILogger<PolicyEvaluationService> _logger;
    private List<PolicyRule>? _policyRules;
    private DateTime _cacheExpiry = DateTime.MinValue;
    private readonly SemaphoreSlim _cacheLock = new(1, 1);

    public PolicyEvaluationService(
        CosmosPolicyRepository policyRepo,
        ILogger<PolicyEvaluationService> logger)
    {
        _policyRepo = policyRepo;
        _logger = logger;
    }

    public async Task<PolicyEvaluationResult> EvaluateAsync(
        string applicationNo,
        CreditProfile credit,
        IncomeVerification income,
        FraudSignals fraud,
        decimal requestedAmount,
        decimal verifiedDtiPct,
        decimal declaredDtiPct,
        decimal paymentToIncomePct)
    {
        var rules = await GetPolicyRulesAsync();

        // Build metrics dictionary
        var metrics = new Dictionary<string, object>
        {
            ["bureau_score"] = credit.BureauScore,
            ["verified_dti_pct"] = verifiedDtiPct,
            ["identity_risk_score"] = fraud.IdentityRiskScore,
            ["loan_amount_requested"] = requestedAmount,
            ["payment_to_income_pct"] = paymentToIncomePct,
            ["declared_dti_pct"] = declaredDtiPct,
            ["watchlist_hit_flag"] = fraud.WatchlistHitFlag,
            ["income_verification_status"] = income.VerificationStatus,
            ["utilization_pct"] = credit.UtilizationPct,
            ["delinquencies_24m"] = credit.Delinquencies24m,
        };

        var hits = new List<PolicyHit>();
        bool hasHardDecline = false;
        bool hasConditional = false;

        foreach (var rule in rules)
        {
            if (!metrics.TryGetValue(rule.Metric, out var rawValue))
            {
                _logger.LogDebug("Metric {Metric} not found for rule {RuleId}, skipping", rule.Metric, rule.RuleId);
                continue;
            }

            bool ruleViolated = EvaluateRule(rawValue, rule.Operator, rule.Threshold);
            string outcome;

            if (ruleViolated)
            {
                if (rule.DecisionEffect == "DECLINE")
                {
                    outcome = "FAIL";
                    hasHardDecline = true;
                }
                else if (rule.DecisionEffect == "CONDITIONAL")
                {
                    outcome = "WARN";
                    hasConditional = true;
                }
                else
                {
                    outcome = "WARN";
                }
            }
            else
            {
                outcome = "PASS";
            }

            hits.Add(new PolicyHit
            {
                RuleId = rule.RuleId,
                Outcome = outcome,
                Severity = rule.Severity,
                Message = rule.Description
            });
        }

        var result = new PolicyEvaluationResult
        {
            ApplicationNo = applicationNo,
            PolicyHits = hits,
            HasHardDecline = hasHardDecline,
            HasConditional = hasConditional,
            TotalRulesEvaluated = rules.Count
        };

        _logger.LogInformation(
            "Policy evaluation for {ApplicationNo}: {TotalRules} rules, {Fails} failures, {Warns} warnings, hardDecline={HardDecline}",
            applicationNo, result.TotalRulesEvaluated,
            hits.Count(h => h.Outcome == "FAIL"),
            hits.Count(h => h.Outcome == "WARN"),
            hasHardDecline);

        return result;
    }

    private bool EvaluateRule(object value, string operatorStr, string threshold)
    {
        // Convert value and threshold to comparable types
        if (double.TryParse(value.ToString(), out double numericValue) &&
            double.TryParse(threshold, out double numericThreshold))
        {
            return operatorStr switch
            {
                ">=" => numericValue >= numericThreshold,
                ">" => numericValue > numericThreshold,
                "<=" => numericValue <= numericThreshold,
                "<" => numericValue < numericThreshold,
                "==" => Math.Abs(numericValue - numericThreshold) < 0.0001,
                "!=" => Math.Abs(numericValue - numericThreshold) >= 0.0001,
                _ => false
            };
        }

        // String comparison
        var stringValue = value.ToString() ?? "";
        return operatorStr switch
        {
            "==" => stringValue.Equals(threshold, StringComparison.OrdinalIgnoreCase),
            "!=" => !stringValue.Equals(threshold, StringComparison.OrdinalIgnoreCase),
            _ => false
        };
    }

    private async Task<List<PolicyRule>> GetPolicyRulesAsync()
    {
        await _cacheLock.WaitAsync();
        try
        {
            if (_policyRules != null && DateTime.UtcNow < _cacheExpiry)
            {
                return _policyRules;
            }

            var allPolicies = await _policyRepo.GetAllAsync();
            
            // Filter to policy rules (POL-* prefix)
            _policyRules = allPolicies
                .OfType<PolicyRule>()
                .Where(p => p.RuleId.StartsWith("POL-"))
                .OrderBy(p => p.RuleId)
                .ToList();

            _cacheExpiry = DateTime.UtcNow.AddMinutes(5);
            _logger.LogInformation("Loaded {Count} policy rules, cached until {Expiry}",
                _policyRules.Count, _cacheExpiry);

            return _policyRules;
        }
        finally
        {
            _cacheLock.Release();
        }
    }
}

public class PolicyEvaluationResult
{
    public string ApplicationNo { get; set; } = string.Empty;
    public List<PolicyHit> PolicyHits { get; set; } = new();
    public bool HasHardDecline { get; set; }
    public bool HasConditional { get; set; }
    public int TotalRulesEvaluated { get; set; }
}

public class PolicyHit
{
    public string RuleId { get; set; } = string.Empty;
    public string Outcome { get; set; } = string.Empty; // PASS, WARN, FAIL
    public string Severity { get; set; } = string.Empty;
    public string Message { get; set; } = string.Empty;
}
