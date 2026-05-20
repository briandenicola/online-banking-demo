using LoanOrigination.Models;
using System.Security.Cryptography;
using System.Text;

namespace LoanOrigination.Services;

/// <summary>
/// Generates deterministic synthetic credit/income/fraud data keyed on applicationNo.
/// Per research R6, same input always yields same output for demo repeatability.
/// Uses SHA-256 hash of applicationNo to seed deterministic random values.
/// </summary>
public class EnrichmentService
{
    private readonly ILogger<EnrichmentService> _logger;

    public EnrichmentService(ILogger<EnrichmentService> logger)
    {
        _logger = logger;
    }

    public CreditProfile GenerateCreditProfile(string applicationNo)
    {
        var seed = GetDeterministicSeed(applicationNo);
        var rng = new Random(seed);

        // Map seed to consistent persona buckets
        var personaKey = seed % 3;
        
        int bureauScore;
        string scoreBand;
        int delinquencies;
        double utilization;
        int hardInquiries;
        
        if (personaKey == 0) // Alice - excellent credit
        {
            bureauScore = rng.Next(760, 820);
            scoreBand = "A";
            delinquencies = 0;
            utilization = rng.Next(5, 25) / 100.0;
            hardInquiries = rng.Next(0, 2);
        }
        else if (personaKey == 1) // Bob - good credit
        {
            bureauScore = rng.Next(680, 740);
            scoreBand = "B";
            delinquencies = rng.Next(0, 2);
            utilization = rng.Next(25, 45) / 100.0;
            hardInquiries = rng.Next(1, 4);
        }
        else // Charlie - subprime
        {
            bureauScore = rng.Next(580, 650);
            scoreBand = "C";
            delinquencies = rng.Next(2, 6);
            utilization = rng.Next(50, 85) / 100.0;
            hardInquiries = rng.Next(3, 8);
        }

        var profile = new CreditProfile
        {
            ApplicationNo = applicationNo,
            BureauScore = bureauScore,
            ScoreBand = scoreBand,
            Delinquencies24m = delinquencies,
            UtilizationPct = utilization,
            HardInquiries6m = hardInquiries,
            BankruptcyFlag = personaKey == 2 && rng.Next(0, 100) < 15 ? "Y" : "N",
            OldestTradeLineMonths = rng.Next(36, 180),
            TotalOpenTradelines = rng.Next(5, 15)
        };

        _logger.LogDebug("Generated credit profile for {ApplicationNo}: score={Score}, band={Band}",
            applicationNo, bureauScore, scoreBand);

        return profile;
    }

    public IncomeVerification GenerateIncomeVerification(string applicationNo, decimal declaredMonthlyIncome)
    {
        var seed = GetDeterministicSeed(applicationNo);
        var rng = new Random(seed);
        var personaKey = seed % 3;

        // Verify income with slight variance from declared
        var variancePct = rng.Next(-5, 10) / 100.0;
        var verifiedIncome = declaredMonthlyIncome * (decimal)(1.0 + variancePct);
        
        string verificationStatus;
        double employerMatchPct;
        int payrollMonths;
        
        if (personaKey == 0) // Alice - fully verified
        {
            verificationStatus = "VERIFIED";
            employerMatchPct = rng.Next(95, 100) / 100.0;
            payrollMonths = rng.Next(24, 48);
        }
        else if (personaKey == 1) // Bob - partially verified
        {
            verificationStatus = "PARTIAL";
            employerMatchPct = rng.Next(75, 95) / 100.0;
            payrollMonths = rng.Next(12, 24);
        }
        else // Charlie - unverified
        {
            verificationStatus = "UNVERIFIED";
            employerMatchPct = rng.Next(40, 75) / 100.0;
            payrollMonths = rng.Next(3, 12);
        }

        var verification = new IncomeVerification
        {
            ApplicationNo = applicationNo,
            VerifiedMonthlyIncome = verifiedIncome,
            VerificationStatus = verificationStatus,
            EmployerMatchPct = (decimal)employerMatchPct,
            PayrollRecordsMonths = payrollMonths,
            IncomeVariancePct = (decimal)Math.Abs(variancePct)
        };

        _logger.LogDebug("Generated income verification for {ApplicationNo}: verified=${Income}, status={Status}",
            applicationNo, verifiedIncome, verificationStatus);

        return verification;
    }

    public FraudSignals GenerateFraudSignals(string applicationNo)
    {
        var seed = GetDeterministicSeed(applicationNo);
        var rng = new Random(seed);
        var personaKey = seed % 3;

        double identityRisk;
        double deviceRisk;
        string addressMismatch;
        string syntheticId;
        string watchlistHit;
        string manualReview;
        
        if (personaKey == 0) // Alice - low risk
        {
            identityRisk = rng.Next(1, 8) / 100.0;
            deviceRisk = rng.Next(1, 10) / 100.0;
            addressMismatch = "N";
            syntheticId = "N";
            watchlistHit = "N";
            manualReview = "N";
        }
        else if (personaKey == 1) // Bob - medium risk
        {
            identityRisk = rng.Next(8, 18) / 100.0;
            deviceRisk = rng.Next(10, 25) / 100.0;
            addressMismatch = rng.Next(0, 100) < 20 ? "Y" : "N";
            syntheticId = "N";
            watchlistHit = "N";
            manualReview = identityRisk > 0.15 ? "Y" : "N";
        }
        else // Charlie - high risk
        {
            identityRisk = rng.Next(20, 45) / 100.0;
            deviceRisk = rng.Next(25, 60) / 100.0;
            addressMismatch = rng.Next(0, 100) < 40 ? "Y" : "N";
            syntheticId = rng.Next(0, 100) < 25 ? "Y" : "N";
            watchlistHit = rng.Next(0, 100) < 15 ? "Y" : "N";
            manualReview = "Y";
        }

        var signals = new FraudSignals
        {
            ApplicationNo = applicationNo,
            IdentityRiskScore = (decimal)identityRisk,
            DeviceRiskScore = (decimal)deviceRisk,
            AddressMismatchFlag = addressMismatch,
            SyntheticIdFlag = syntheticId,
            WatchlistHitFlag = watchlistHit,
            RecommendedManualReview = manualReview
        };

        _logger.LogDebug("Generated fraud signals for {ApplicationNo}: identityRisk={Risk}, manualReview={Review}",
            applicationNo, identityRisk, manualReview);

        return signals;
    }

    private int GetDeterministicSeed(string applicationNo)
    {
        using var sha256 = SHA256.Create();
        var hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(applicationNo));
        // Use first 4 bytes as seed
        return BitConverter.ToInt32(hash, 0);
    }
}
