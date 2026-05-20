using LoanOrigination.Models;
using LoanOrigination.Repositories;

namespace LoanOrigination.Services;

/// <summary>
/// Computes loan pricing (APR, monthly payment, total repayable) based on
/// risk tier and term. Loads pricing matrix from Cosmos seed data.
/// Formula: P = L × c(1+c)^n / ((1+c)^n − 1)
/// </summary>
public class PricingService
{
    private readonly CosmosPolicyRepository _policyRepo;
    private readonly ILogger<PricingService> _logger;
    private List<ProductPricing>? _pricingMatrix;
    private DateTime _cacheExpiry = DateTime.MinValue;
    private readonly SemaphoreSlim _cacheLock = new(1, 1);

    public PricingService(
        CosmosPolicyRepository policyRepo,
        ILogger<PricingService> logger)
    {
        _policyRepo = policyRepo;
        _logger = logger;
    }

    public async Task<PricingResult> ComputeQuoteAsync(
        string applicationNo,
        decimal requestedAmount,
        int termMonths,
        string loanType,
        int creditScore)
    {
        // Determine risk tier from credit score
        string riskTier = creditScore >= 740 ? "A" :
                         creditScore >= 680 ? "B" : "C";

        // Load pricing matrix (cached for 5 minutes)
        var matrix = await GetPricingMatrixAsync();

        // Find matching pricing rule
        var rule = matrix
            .Where(p => p.RiskTier == riskTier 
                     && p.LoanType == loanType 
                     && p.TermMonths == termMonths
                     && p.MinAmount <= requestedAmount 
                     && requestedAmount <= p.MaxAmount)
            .FirstOrDefault();

        // Fallback: try same tier and type
        rule ??= matrix
            .Where(p => p.RiskTier == riskTier && p.LoanType == loanType)
            .OrderBy(p => Math.Abs(p.TermMonths - termMonths))
            .FirstOrDefault();

        // Fallback: try same tier, any type
        rule ??= matrix
            .Where(p => p.RiskTier == riskTier)
            .FirstOrDefault();

        // Fallback: first rule in matrix
        rule ??= matrix.First();

        decimal aprPct = rule.AprPct;
        double monthlyRate = (double)(aprPct / 100m / 12m);
        
        decimal monthlyPayment;
        if (monthlyRate > 0)
        {
            // Amortization formula
            double factor = Math.Pow(1 + monthlyRate, termMonths);
            monthlyPayment = requestedAmount * (decimal)(monthlyRate * factor / (factor - 1));
        }
        else
        {
            // Zero-interest case
            monthlyPayment = requestedAmount / termMonths;
        }

        monthlyPayment = Math.Round(monthlyPayment, 2);
        decimal totalRepayable = Math.Round(monthlyPayment * termMonths, 2);
        DateTime originationDate = DateTime.UtcNow;
        DateTime payoffDate = originationDate.AddMonths(termMonths);

        var result = new PricingResult
        {
            ApplicationNo = applicationNo,
            RiskTier = riskTier,
            AprPct = aprPct,
            EstimatedMonthlyPayment = monthlyPayment,
            TotalRepayableAmount = totalRepayable,
            PricingRuleId = rule.PricingRuleId,
            OriginationDate = originationDate,
            PayoffDate = payoffDate
        };

        _logger.LogDebug(
            "Computed pricing for {ApplicationNo}: tier={Tier}, APR={Apr}%, payment=${Payment}/mo, total=${Total}",
            applicationNo, riskTier, aprPct, monthlyPayment, totalRepayable);

        return result;
    }

    private async Task<List<ProductPricing>> GetPricingMatrixAsync()
    {
        await _cacheLock.WaitAsync();
        try
        {
            if (_pricingMatrix != null && DateTime.UtcNow < _cacheExpiry)
            {
                return _pricingMatrix;
            }

            // Load from Cosmos loan-policy container (shares space with policy rules)
            var allPolicies = await _policyRepo.GetAllAsync();
            
            // Filter to pricing rules (identified by PricingRuleId prefix "PRC-")
            _pricingMatrix = allPolicies
                .OfType<ProductPricing>()
                .Where(p => !string.IsNullOrEmpty(p.PricingRuleId))
                .ToList();

            // If no pricing rules found, return default matrix
            if (_pricingMatrix.Count == 0)
            {
                _logger.LogWarning("No pricing rules found in loan-policy container, using default matrix");
                _pricingMatrix = GetDefaultPricingMatrix();
            }

            _cacheExpiry = DateTime.UtcNow.AddMinutes(5);
            _logger.LogInformation("Loaded {Count} pricing rules, cached until {Expiry}",
                _pricingMatrix.Count, _cacheExpiry);

            return _pricingMatrix;
        }
        finally
        {
            _cacheLock.Release();
        }
    }

    private List<ProductPricing> GetDefaultPricingMatrix()
    {
        // Fallback pricing matrix if seed data is missing
        return new List<ProductPricing>
        {
            new() { PricingRuleId = "PRC-DEFAULT-A-PERSONAL-36", RiskTier = "A", LoanType = "personal", TermMonths = 36, MinAmount = 1000, MaxAmount = 500000, MinCreditScore = 740, MaxDtiPct = 0.40m, AprPct = 7.49m },
            new() { PricingRuleId = "PRC-DEFAULT-B-PERSONAL-36", RiskTier = "B", LoanType = "personal", TermMonths = 36, MinAmount = 1000, MaxAmount = 500000, MinCreditScore = 680, MaxDtiPct = 0.40m, AprPct = 12.99m },
            new() { PricingRuleId = "PRC-DEFAULT-C-PERSONAL-36", RiskTier = "C", LoanType = "personal", TermMonths = 36, MinAmount = 1000, MaxAmount = 250000, MinCreditScore = 620, MaxDtiPct = 0.35m, AprPct = 19.99m },
        };
    }
}

public class PricingResult
{
    public string ApplicationNo { get; set; } = string.Empty;
    public string RiskTier { get; set; } = string.Empty;
    public decimal AprPct { get; set; }
    public decimal EstimatedMonthlyPayment { get; set; }
    public decimal TotalRepayableAmount { get; set; }
    public string PricingRuleId { get; set; } = string.Empty;
    public DateTime OriginationDate { get; set; }
    public DateTime PayoffDate { get; set; }
}
