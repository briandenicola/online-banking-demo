using Azure.AI.Projects;
using LoanOrigination.Models;
using LoanOrigination.Repositories;
using LoanOrigination.Services;
using LoanOrigination.Telemetry;
using System.Diagnostics;
using System.Text.Json;

namespace LoanOrigination.Agents;

/// <summary>
/// Code-based coordinator orchestrating S01-S10 workflow by calling Foundry agents sequentially.
/// Compiles a comprehensive brief from specialist agents and passes it to the underwriting agent.
/// </summary>
public class LoanAgentOrchestrator : ILoanAgentOrchestrator
{
    private readonly AIProjectClient? _projectClient;
    private readonly EnrichmentService _enrichmentService;
    private readonly PricingService _pricingService;
    private readonly PolicyEvaluationService _policyEvaluationService;
    private readonly ILoanRunRepository _runRepo;
    private readonly ILogger<LoanAgentOrchestrator> _logger;

    public LoanAgentOrchestrator(
        AIProjectClient? projectClient,
        EnrichmentService enrichmentService,
        PricingService pricingService,
        PolicyEvaluationService policyEvaluationService,
        ILoanRunRepository runRepo,
        ILogger<LoanAgentOrchestrator> logger)
    {
        _projectClient = projectClient;
        _enrichmentService = enrichmentService;
        _pricingService = pricingService;
        _policyEvaluationService = policyEvaluationService;
        _runRepo = runRepo;
        _logger = logger;
    }

    public async Task<bool> HealthCheckAsync()
    {
        if (_projectClient == null)
        {
            _logger.LogWarning("Health check: AIProjectClient not configured");
            return false;
        }

        try
        {
            _logger.LogInformation("Running Foundry health check...");
            
            await foreach (var agent in _projectClient.Agents.GetAgentsAsync())
            {
                if (agent.Name == "health-check-agent")
                {
                    _logger.LogInformation("Health check passed: health-check-agent found");
                    return true;
                }
            }
            
            _logger.LogWarning("Health check failed: health-check-agent not found");
            return false;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Health check failed: {Error}", ex.Message);
            return false;
        }
    }

    public async Task<AgentRunResponse> RunWorkflowAsync(
        LoanApplication application,
        Action<string, string, string>? onStepUpdate = null)
    {
        var sw = Stopwatch.StartNew();
        var runId = $"RUN-{DateTime.UtcNow:yyyy}-{Guid.NewGuid().ToString("N")[..7].ToUpper()}";
        var applicationNo = application.ApplicationNo;

        using var activity = WorkflowTelemetry.StartWorkflowActivity("LoanOrigination", applicationNo, runId);
        activity?.SetTag("loan.execution_mode", "code_coordinator");

        _logger.LogInformation("=== Starting workflow {RunId} for application {ApplicationNo} ===",
            runId, applicationNo);

        if (_projectClient == null)
        {
            _logger.LogError("❌ AIProjectClient not configured, cannot run workflow");
            throw new InvalidOperationException("Azure AI Foundry is not configured");
        }

        var workflowLog = new List<WorkflowStep>();

        // ═══ S01: Application Intake ═══
        using (var s01Activity = WorkflowTelemetry.StartStepActivity("S01", applicationNo, runId))
        {
            onStepUpdate?.Invoke("S01", "running", "Loading application...");
            workflowLog.Add(new WorkflowStep
            {
                StepId = "S01",
                StepName = "Application Intake",
                Status = "completed",
                Timestamp = DateTime.UtcNow,
                Detail = $"Application {applicationNo} loaded"
            });
            onStepUpdate?.Invoke("S01", "completed", $"Application {applicationNo} loaded");
        }

        // ═══ S02: Data Enrichment ═══
        CreditProfile credit;
        IncomeVerification income;
        FraudSignals fraud;
        PricingResult pricing;
        decimal verifiedDti;

        using (var s02Activity = WorkflowTelemetry.StartStepActivity("S02", applicationNo, runId))
        {
            onStepUpdate?.Invoke("S02", "running", "Enriching data...");
            
            credit = _enrichmentService.GenerateCreditProfile(applicationNo);
            income = _enrichmentService.GenerateIncomeVerification(
                applicationNo,
                application.Financials.MonthlyNetIncome);
            fraud = _enrichmentService.GenerateFraudSignals(applicationNo);
            pricing = await _pricingService.ComputeQuoteAsync(
                applicationNo,
                application.LoanRequest.Amount,
                application.LoanRequest.TermMonths,
                application.LoanRequest.LoanType,
                credit.BureauScore);

            verifiedDti = income.VerifiedMonthlyIncome > 0
                ? application.Financials.TotalMonthlyDebtPayments / income.VerifiedMonthlyIncome
                : 999m;

            workflowLog.Add(new WorkflowStep
            {
                StepId = "S02",
                StepName = "Data Enrichment",
                Status = "completed",
                Timestamp = DateTime.UtcNow,
                Detail = "Credit, income, fraud, pricing enriched"
            });
            
            onStepUpdate?.Invoke("S02", "completed", "Enrichment complete");
        }

        // Build enriched context JSON for agent prompts
        var enrichedContext = JsonSerializer.Serialize(new
        {
            application = new
            {
                application_no = applicationNo,
                applicant_name = application.Applicant.Name,
                loan_amount = application.LoanRequest.Amount,
                loan_purpose = application.LoanRequest.Purpose,
                term_months = application.LoanRequest.TermMonths,
                loan_type = application.LoanRequest.LoanType,
                gross_annual_income = application.Financials.GrossAnnualIncome,
                monthly_net_income = application.Financials.MonthlyNetIncome,
                monthly_debt = application.Financials.TotalMonthlyDebtPayments,
                declared_dti_pct = application.Financials.DeclaredDtiPct,
            },
            credit_profile = credit,
            income_verification = income,
            fraud_signals = fraud,
            pricing_quote = new
            {
                risk_tier = pricing.RiskTier,
                apr_pct = pricing.AprPct,
                monthly_payment = pricing.EstimatedMonthlyPayment,
                payment_to_income_pct = (double)(pricing.EstimatedMonthlyPayment / income.VerifiedMonthlyIncome),
            },
            verified_dti_pct = (double)verifiedDti,
        }, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = false });

        // Resolve agents from Foundry
        var agentMap = new Dictionary<string, string>();
        await foreach (var agent in _projectClient.Agents.GetAgentsAsync())
        {
            agentMap[agent.Name] = agent.Id;
        }
        _logger.LogInformation("[{RunId}] Resolved {Count} agents from Foundry", runId, agentMap.Count);

        // ═══ S03-S08: Specialist Agents ═══
        var specialistResults = new Dictionary<string, string>();
        var specialists = new (string stepId, string stepName, string agentName, string promptSnippet)[]
        {
            ("S03", "Credit Profile Analysis", "credit-profile-agent",
                "Analyze the credit profile for this loan application. Provide a structured risk assessment covering bureau score, delinquencies, utilization, and credit age."),
            ("S04", "Income Verification Analysis", "income-verification-agent",
                "Verify the income data for this loan application. Assess verification confidence, employer match, income stability, and affordability."),
            ("S05", "Fraud Screening Analysis", "fraud-screening-agent",
                "Screen this loan application for fraud signals. Classify the fraud risk level, check identity verification, device signals, and watchlist matches."),
            ("S06", "Policy Evaluation", "policy-evaluation-agent",
                "Evaluate this loan application against all underwriting policy rules POL-001 through POL-010. Provide per-rule PASS/FAIL assessment with reasoning."),
            ("S08", "Pricing Analysis", "pricing-agent",
                "Review the pricing data in this loan application. Validate the risk tier assignment, quoted APR, and monthly payment calculations."),
        };

        foreach (var (stepId, stepName, agentName, promptSnippet) in specialists)
        {
            using var stepActivity = WorkflowTelemetry.StartStepActivity(stepId, applicationNo, runId);
            stepActivity?.SetTag("agent.name", agentName);
            
            onStepUpdate?.Invoke(stepId, "running", $"Calling {agentName}...");
            
            try
            {
                var agentSw = Stopwatch.StartNew();
                var prompt = $"{promptSnippet}\n\nAPPLICATION DATA:\n{enrichedContext}";
                
                if (!agentMap.TryGetValue(agentName, out var agentId))
                {
                    _logger.LogWarning("[{RunId}] Agent '{AgentName}' not found in Foundry, skipping", runId, agentName);
                    specialistResults[stepId] = $"Agent '{agentName}' not found in Foundry.";
                    workflowLog.Add(new WorkflowStep
                    {
                        StepId = stepId,
                        StepName = stepName,
                        Status = "failed",
                        Timestamp = DateTime.UtcNow,
                        AgentName = agentName,
                        Detail = "Agent not found"
                    });
                    onStepUpdate?.Invoke(stepId, "failed", "Agent not found");
                    continue;
                }

                // Azure.AI.Projects 2.0.0-beta.2: GetAIAgentAsync API not yet available
                // Stub for online mode — use offline mode (Foundry__Mode=offline) for MVP
                throw new NotImplementedException(
                    "Foundry online mode pending Azure.AI.Projects 2.0.0-beta.2 API resolution. " +
                    "Use Foundry__Mode=offline for MVP. See GitHub issue: loan-origination-service online orchestrator completion.");
                
                // Expected API pattern (pending SDK update):
                // var agent = await _projectClient.GetAIAgentAsync(agentId);
                // var response = await agent.RunAsync(prompt);
                // var responseText = response.Text ?? "(empty response)";
                // agentSw.Stop();
                // specialistResults[stepId] = responseText;
                // workflowLog.Add(new WorkflowStep { ..., Detail = $"{agentName} completed ({agentSw.ElapsedMilliseconds}ms, {responseText.Length} chars)" });
                
                #pragma warning disable CS0162 // Unreachable code detected
                /*
                var agent = await _projectClient.GetAIAgentAsync(agentId);
                var response = await agent.RunAsync(prompt);
                var responseText = response.Text ?? "(empty response)";
                
                agentSw.Stop();
                specialistResults[stepId] = responseText;
                */

                workflowLog.Add(new WorkflowStep
                {
                    StepId = stepId,
                    StepName = stepName,
                    Status = "completed",
                    Timestamp = DateTime.UtcNow,
                    AgentName = agentName,
                    Detail = $"Stubbed (online mode not implemented)"
                });
                
                _logger.LogInformation("[{RunId}] {StepId}: {AgentName} stubbed (online mode not implemented)",
                    runId, stepId, agentName);
                #pragma warning restore CS0162
                
                onStepUpdate?.Invoke(stepId, "completed", $"{agentName} done");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[{RunId}] {StepId}: Agent '{AgentName}' failed: {Error}",
                    runId, stepId, agentName, ex.Message);
                
                specialistResults[stepId] = $"ERROR: {ex.Message}";
                workflowLog.Add(new WorkflowStep
                {
                    StepId = stepId,
                    StepName = stepName,
                    Status = "failed",
                    Timestamp = DateTime.UtcNow,
                    AgentName = agentName,
                    Detail = $"Error: {ex.Message}"
                });
                onStepUpdate?.Invoke(stepId, "failed", $"Error: {ex.Message}");
            }
        }

        // ═══ S07: DTI & Affordability ═══
        using (var s07Activity = WorkflowTelemetry.StartStepActivity("S07", applicationNo, runId))
        {
            onStepUpdate?.Invoke("S07", "running", "Computing DTI...");
            
            var policyEval = await _policyEvaluationService.EvaluateAsync(
                applicationNo, credit, income, fraud,
                application.LoanRequest.Amount, verifiedDti,
                application.Financials.DeclaredDtiPct,
                pricing.EstimatedMonthlyPayment / income.VerifiedMonthlyIncome);

            workflowLog.Add(new WorkflowStep
            {
                StepId = "S07",
                StepName = "DTI & Affordability",
                Status = "completed",
                Timestamp = DateTime.UtcNow,
                Detail = $"Verified DTI: {verifiedDti:P1}, {policyEval.PolicyHits.Count(h => h.Outcome == "FAIL")} policy failures"
            });
            onStepUpdate?.Invoke("S07", "completed", $"DTI {verifiedDti:P1}");
        }

        // ═══ Compile Comprehensive Brief ═══
        var briefBuilder = new System.Text.StringBuilder();
        briefBuilder.AppendLine("You are the final underwriting recommendation agent. Below is the ORIGINAL APPLICATION DATA followed by COMPLETE ANALYSIS from each specialist agent. Use ALL of this information to produce your final recommendation.");
        briefBuilder.AppendLine();
        briefBuilder.AppendLine("═══════════════════════════════════════════");
        briefBuilder.AppendLine("SECTION 1: ORIGINAL APPLICATION DATA");
        briefBuilder.AppendLine("═══════════════════════════════════════════");
        briefBuilder.AppendLine(enrichedContext);
        briefBuilder.AppendLine();

        var sectionNames = new Dictionary<string, string>
        {
            ["S03"] = "CREDIT PROFILE ANALYSIS (credit-profile-agent)",
            ["S04"] = "INCOME VERIFICATION ANALYSIS (income-verification-agent)",
            ["S05"] = "FRAUD SCREENING ANALYSIS (fraud-screening-agent)",
            ["S06"] = "POLICY EVALUATION (policy-evaluation-agent)",
            ["S08"] = "PRICING ANALYSIS (pricing-agent)",
        };

        int sectionNum = 2;
        foreach (var (stepId, sectionName) in sectionNames)
        {
            briefBuilder.AppendLine("═══════════════════════════════════════════");
            briefBuilder.AppendLine($"SECTION {sectionNum}: {sectionName}");
            briefBuilder.AppendLine("═══════════════════════════════════════════");
            briefBuilder.AppendLine(specialistResults.GetValueOrDefault(stepId, "(no response)"));
            briefBuilder.AppendLine();
            sectionNum++;
        }

        briefBuilder.AppendLine("═══════════════════════════════════════════");
        briefBuilder.AppendLine("YOUR TASK — FINAL UNDERWRITING RECOMMENDATION");
        briefBuilder.AppendLine("═══════════════════════════════════════════");
        briefBuilder.AppendLine("Based on ALL of the above specialist analyses and the original application data, produce your FINAL UNDERWRITING RECOMMENDATION including:");
        briefBuilder.AppendLine("1. Recommendation status: APPROVE, CONDITIONAL, or DECLINE");
        briefBuilder.AppendLine("2. Confidence score (0.0 to 1.0)");
        briefBuilder.AppendLine("3. Key risk factors and mitigating factors");
        briefBuilder.AppendLine("4. Conditions (if CONDITIONAL)");
        briefBuilder.AppendLine("5. Professional rationale summary for a human reviewer");

        var comprehensiveBrief = briefBuilder.ToString();

        // ═══ S09: Underwriting Recommendation Agent ═══
        string underwritingResponse;
        using (var s09Activity = WorkflowTelemetry.StartStepActivity("S09", applicationNo, runId))
        {
            s09Activity?.SetTag("agent.name", "underwriting-recommendation-agent");
            onStepUpdate?.Invoke("S09", "running", "Calling underwriting-recommendation-agent...");
            
            try
            {
                var agentSw = Stopwatch.StartNew();
                
                if (!agentMap.TryGetValue("underwriting-recommendation-agent", out var agentId))
                {
                    throw new InvalidOperationException("underwriting-recommendation-agent not found in Foundry");
                }

                // Azure.AI.Projects 2.0.0-beta.2: GetAIAgentAsync API not yet available
                // Stub for online mode — use offline mode (Foundry__Mode=offline) for MVP
                throw new NotImplementedException(
                    "Foundry online mode pending Azure.AI.Projects 2.0.0-beta.2 API resolution. " +
                    "Use Foundry__Mode=offline for MVP. See GitHub issue: loan-origination-service online orchestrator completion.");
                
                // Expected API pattern (pending SDK update):
                // var agent = await _projectClient.GetAIAgentAsync(agentId);
                // var response = await agent.RunAsync(comprehensiveBrief);
                // underwritingResponse = response.Text ?? "(empty response)";
                
                #pragma warning disable CS0162 // Unreachable code detected
                /*
                var agent = await _projectClient.GetAIAgentAsync(agentId);
                var response = await agent.RunAsync(comprehensiveBrief);
                underwritingResponse = response.Text ?? "(empty response)";
                
                agentSw.Stop();
                */
                
                underwritingResponse = "Stubbed underwriting response (online mode not implemented)";
                #pragma warning restore CS0162
                
                workflowLog.Add(new WorkflowStep
                {
                    StepId = "S09",
                    StepName = "Underwriting Recommendation",
                    Status = "completed",
                    Timestamp = DateTime.UtcNow,
                    AgentName = "underwriting-recommendation-agent",
                    Detail = $"Recommendation ready ({agentSw.ElapsedMilliseconds}ms, {underwritingResponse.Length} chars)"
                });
                
                _logger.LogInformation("[{RunId}] S09: Underwriting agent completed in {Duration}ms",
                    runId, agentSw.ElapsedMilliseconds);
                
                onStepUpdate?.Invoke("S09", "completed", "Recommendation ready");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "[{RunId}] ❌ Underwriting agent failed: {Error}", runId, ex.Message);
                throw new InvalidOperationException($"Underwriting agent failed: {ex.Message}", ex);
            }
        }

        // ═══ S10: Human Review Ready ═══
        workflowLog.Add(new WorkflowStep
        {
            StepId = "S10",
            StepName = "Human Review Ready",
            Status = "completed",
            Timestamp = DateTime.UtcNow,
            Detail = "Packaged for reviewer"
        });
        onStepUpdate?.Invoke("S10", "completed", "Ready for human review");

        // ═══ Build Response ═══
        sw.Stop();

        // Parse recommendation from AI response (simple heuristic)
        string recommendationStatus = "APPROVE";
        decimal confidence = 0.75m;
        if (underwritingResponse.Contains("DECLINE", StringComparison.OrdinalIgnoreCase))
        {
            recommendationStatus = "DECLINE";
            confidence = 0.65m;
        }
        else if (underwritingResponse.Contains("CONDITIONAL", StringComparison.OrdinalIgnoreCase))
        {
            recommendationStatus = "CONDITIONAL";
            confidence = 0.70m;
        }

        var recommendation = new UnderwritingRecommendation
        {
            Recommendation = recommendationStatus,
            Confidence = confidence,
            Rationale = underwritingResponse,
            RiskFactors = new List<string>(),
            Strengths = new List<string>(),
            Conditions = new List<string>()
        };

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

        _logger.LogInformation("=== Workflow complete: {RunId}, duration={Duration}ms, recommendation={Status} ===",
            runId, sw.ElapsedMilliseconds, recommendationStatus);

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
}
