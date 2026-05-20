using LoanOrigination.Models;
using LoanOrigination.Repositories;
using LoanOrigination.Services;
using LoanOrigination.Telemetry;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;

namespace LoanOrigination.Agents;

/// <summary>
/// Offline orchestrator for local development (Foundry__Mode=offline).
/// Returns deterministic canned recommendations keyed on applicationNo hash.
/// Reuses EnrichmentService for signal generation. No Foundry calls.
/// Alice → APPROVE, Bob → CONDITIONAL, Charlie → DECLINE.
/// </summary>
public class OfflineLoanAgentOrchestrator : ILoanAgentOrchestrator
{
    private readonly EnrichmentService _enrichmentService;
    private readonly PricingService _pricingService;
    private readonly PolicyEvaluationService _policyEvaluationService;
    private readonly ILoanRunRepository _runRepo;
    private readonly ILogger<OfflineLoanAgentOrchestrator> _logger;

    public OfflineLoanAgentOrchestrator(
        EnrichmentService enrichmentService,
        PricingService pricingService,
        PolicyEvaluationService policyEvaluationService,
        ILoanRunRepository runRepo,
        ILogger<OfflineLoanAgentOrchestrator> logger)
    {
        _enrichmentService = enrichmentService;
        _pricingService = pricingService;
        _policyEvaluationService = policyEvaluationService;
        _runRepo = runRepo;
        _logger = logger;
    }

    public Task<bool> HealthCheckAsync()
    {
        _logger.LogInformation("Offline mode health check: always true");
        return Task.FromResult(true);
    }

    public async Task<AgentRunResponse> RunWorkflowAsync(
        LoanApplication application,
        Action<string, string, string>? onStepUpdate = null)
    {
        var sw = Stopwatch.StartNew();
        var runId = $"RUN-{DateTime.UtcNow:yyyy}-{Guid.NewGuid().ToString("N")[..7].ToUpper()}";
        var applicationNo = application.ApplicationNo;

        using var activity = WorkflowTelemetry.StartWorkflowActivity(applicationNo, runId);
        activity?.SetTag("loan.execution_mode", "offline");

        _logger.LogInformation("=== Starting OFFLINE workflow {RunId} for application {ApplicationNo} ===",
            runId, applicationNo);

        var workflowLog = new List<WorkflowStep>();

        // Simulate step progression
        var steps = new[]
        {
            ("S01", "Application Intake", "Application loaded"),
            ("S02", "Data Enrichment", "Enrichment complete"),
            ("S03", "Credit Profile Analysis", "Credit analyzed"),
            ("S04", "Income Verification Analysis", "Income verified"),
            ("S05", "Fraud Screening Analysis", "Fraud screened"),
            ("S06", "Policy Evaluation", "Policies evaluated"),
            ("S07", "DTI & Affordability", "DTI computed"),
            ("S08", "Pricing Analysis", "Pricing complete"),
            ("S09", "Underwriting Recommendation", "Recommendation ready"),
            ("S10", "Human Review Ready", "Ready for review"),
        };

        foreach (var (stepId, stepName, detail) in steps)
        {
            using var stepActivity = WorkflowTelemetry.StartStepActivity(stepId, applicationNo, runId);
            onStepUpdate?.Invoke(stepId, "running", $"Processing {stepName}...");
            
            // Simulate processing delay
            await Task.Delay(50);
            
            workflowLog.Add(new WorkflowStep
            {
                StepId = stepId,
                StepName = stepName,
                Status = "completed",
                Timestamp = DateTime.UtcNow,
                AgentName = stepId == "S09" ? "offline-underwriting-agent" : null,
                Detail = $"{detail} (offline mode)"
            });
            
            onStepUpdate?.Invoke(stepId, "completed", detail);
        }

        // Generate enrichment data
        var credit = _enrichmentService.GenerateCreditProfile(applicationNo);
        var income = _enrichmentService.GenerateIncomeVerification(
            applicationNo,
            application.Financials.MonthlyNetIncome);
        var fraud = _enrichmentService.GenerateFraudSignals(applicationNo);
        var pricing = await _pricingService.ComputeQuoteAsync(
            applicationNo,
            application.LoanRequest.Amount,
            application.LoanRequest.TermMonths,
            application.LoanRequest.LoanType,
            credit.BureauScore);

        // Deterministic recommendation based on persona (via applicationNo hash)
        var seed = GetDeterministicSeed(applicationNo);
        var personaKey = seed % 3;
        
        string recommendationStatus;
        decimal confidence;
        string rationale;
        
        if (personaKey == 0) // Alice - APPROVE
        {
            recommendationStatus = "APPROVE";
            confidence = 0.83m;
            rationale = "Strong credit profile (score {0}), verified income ${1:N0}/mo, low fraud risk ({2:P0}). All policy checks pass. Recommend full approval at quoted terms.";
            rationale = string.Format(rationale, credit.BureauScore, income.VerifiedMonthlyIncome, fraud.IdentityRiskScore);
        }
        else if (personaKey == 1) // Bob - CONDITIONAL
        {
            recommendationStatus = "CONDITIONAL";
            confidence = 0.68m;
            rationale = "Moderate credit profile (score {0}), income verification {1}, elevated fraud risk ({2:P0}). Conditional approval pending: (1) Enhanced identity verification, (2) Income documentation review. Recommend approval with conditions.";
            rationale = string.Format(rationale, credit.BureauScore, income.VerificationStatus, fraud.IdentityRiskScore);
        }
        else // Charlie - DECLINE
        {
            recommendationStatus = "DECLINE";
            confidence = 0.72m;
            rationale = "Subprime credit profile (score {0}), unverified income, high fraud risk ({1:P0}). Policy failures detected. Recommend decline due to elevated risk profile and policy violations.";
            rationale = string.Format(rationale, credit.BureauScore, fraud.IdentityRiskScore);
        }

        var recommendation = new UnderwritingRecommendation
        {
            Recommendation = recommendationStatus,
            Confidence = confidence,
            Rationale = rationale,
            RiskFactors = personaKey == 2 ? new List<string> { "Subprime credit", "High fraud risk" } : new List<string>(),
            Strengths = personaKey == 0 ? new List<string> { "Excellent credit", "Low fraud risk" } : new List<string>(),
            Conditions = personaKey == 1 ? new List<string> { "Enhanced identity verification", "Income documentation review" } : new List<string>()
        };

        sw.Stop();

        var verifiedDti = income.VerifiedMonthlyIncome > 0
            ? application.Financials.TotalMonthlyDebtPayments / income.VerifiedMonthlyIncome
            : 999m;

        var runRecord = new LoanRun
        {
            Id = runId,
            RunId = runId,
            ApplicationNo = applicationNo,
            StartedAt = DateTime.UtcNow.AddMilliseconds(-sw.ElapsedMilliseconds),
            CompletedAt = DateTime.UtcNow,
            DurationMs = sw.ElapsedMilliseconds,
            TriggerKind = "run",
            Prepared = new PreparedData
            {
                CreditProfile = credit,
                IncomeVerification = income,
                FraudSignals = fraud,
                PricingQuote = new ProductPricing
                {
                    RiskTier = pricing.RiskTier,
                    AprPct = pricing.AprPct,
                    PricingRuleId = pricing.PricingRuleId
                }
            },
            WorkflowLog = workflowLog,
            Recommendation = recommendation,
            Errors = new List<string>()
        };

        await _runRepo.CreateAsync(runRecord);

        _logger.LogInformation("=== OFFLINE workflow complete: {RunId}, duration={Duration}ms, recommendation={Status} (persona={Persona}) ===",
            runId, sw.ElapsedMilliseconds, recommendationStatus, personaKey == 0 ? "Alice" : personaKey == 1 ? "Bob" : "Charlie");

        return new AgentRunResponse
        {
            RunId = runId,
            ApplicationNo = applicationNo,
            StartedAt = runRecord.StartedAt,
            CompletedAt = runRecord.CompletedAt.Value,
            DurationMs = sw.ElapsedMilliseconds,
            WorkflowLog = workflowLog,
            Recommendation = recommendation,
            Errors = new List<string>()
        };
    }

    private int GetDeterministicSeed(string applicationNo)
    {
        using var sha256 = SHA256.Create();
        var hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(applicationNo));
        return BitConverter.ToInt32(hash, 0);
    }
}
