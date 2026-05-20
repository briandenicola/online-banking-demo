using System.ComponentModel.DataAnnotations;
using LoanOrigination.Agents;
using LoanOrigination.Models;
using LoanOrigination.Repositories;
using LoanOrigination.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace LoanOrigination.Controllers;

[ApiController]
[Route("api/loans")]
public class LoansController : ControllerBase
{
    private readonly ILoanApplicationRepository _applicationRepo;
    private readonly ILoanRunRepository _runRepo;
    private readonly ILoanAgentOrchestrator _orchestrator;
    private readonly ApplicationNumberGenerator _appNumberGen;
    private readonly UserLookupService _userLookup;
    private readonly ILogger<LoansController> _logger;

    private static readonly string[] AllowedLoanTypes = { "personal", "auto", "mortgage", "small_business" };
    private static readonly int[] AllowedTerms = { 12, 24, 36, 48, 60, 72, 84, 120, 180, 240, 360 };

    public LoansController(
        ILoanApplicationRepository applicationRepo,
        ILoanRunRepository runRepo,
        ILoanAgentOrchestrator orchestrator,
        ApplicationNumberGenerator appNumberGen,
        UserLookupService userLookup,
        ILogger<LoansController> logger)
    {
        _applicationRepo = applicationRepo;
        _runRepo = runRepo;
        _orchestrator = orchestrator;
        _appNumberGen = appNumberGen;
        _userLookup = userLookup;
        _logger = logger;
    }

    /// <summary>
    /// POST /api/loans/applications — Submit a new loan application.
    /// </summary>
    [HttpPost("applications")]
    [Authorize(Roles = "User")]
    public async Task<IActionResult> CreateApplication([FromBody] CreateLoanApplicationRequest request)
    {
        // Extract userId from JWT claims (NEVER from body)
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized(new { error = "User ID claim not found in token" });
        }

        // Validate request
        var validationResult = ValidateRequest(request);
        if (validationResult != null)
        {
            return BadRequest(validationResult);
        }

        // Default applicant identity from user-service
        var user = await _userLookup.GetUserAsync(userId);
        if (user == null)
        {
            _logger.LogWarning("User {UserId} not found in user-service", userId);
            return BadRequest(new { error = "User not found", field = "userId" });
        }

        // Generate unique application number
        var applicationNo = await _appNumberGen.GenerateUniqueAsync(async (appNo) =>
        {
            var existing = await _applicationRepo.GetByIdAsync(appNo);
            return existing != null;
        });

        var application = new LoanApplication
        {
            Id = applicationNo,
            ApplicationNo = applicationNo,
            UserId = userId,
            ApplicationDate = DateTime.UtcNow,
            Status = "submitted",
            Applicant = new ApplicantInfo
            {
                Name = request.Applicant?.Name ?? $"{user.FirstName} {user.LastName}",
                Dob = request.Applicant?.Dob ?? user.DateOfBirth ?? "1980-01-01",
                SsnLast4 = request.Applicant?.SsnLast4 ?? "0000",
                Phone = request.Applicant?.Phone ?? user.Phone ?? "",
                Email = request.Applicant?.Email ?? user.Email,
                CurrentAddress = request.Applicant?.CurrentAddress ?? "",
                CityStateZip = request.Applicant?.CityStateZip ?? ""
            },
            LoanRequest = request.LoanRequest,
            Financials = request.Financials
        };

        try
        {
            var created = await _applicationRepo.CreateAsync(application);
            
            _logger.LogInformation("Created loan application {ApplicationNo} for user {UserId}, amount=${Amount}, term={Term}mo",
                created.ApplicationNo, userId, created.LoanRequest.Amount, created.LoanRequest.TermMonths);

            return CreatedAtAction(
                nameof(GetApplication),
                new { applicationNo = created.ApplicationNo },
                new
                {
                    created.ApplicationNo,
                    created.UserId,
                    created.ApplicationDate,
                    created.Status,
                    created.LoanRequest,
                    created.Financials
                });
        }
        catch (Exception ex)
        {
            var correlationId = HttpContext.TraceIdentifier;
            _logger.LogError(ex, "Failed to create loan application for user {UserId}. CorrelationId: {CorrelationId}",
                userId, correlationId);
            return StatusCode(500, new { error = "An internal error occurred", correlationId });
        }
    }

    /// <summary>
    /// GET /api/loans/applications/{applicationNo} — Get application + last run + last decision.
    /// </summary>
    [HttpGet("applications/{applicationNo}")]
    [Authorize(Roles = "User,Admin")]
    public async Task<IActionResult> GetApplication(string applicationNo)
    {
        var application = await _applicationRepo.GetByIdAsync(applicationNo);
        if (application == null)
        {
            return NotFound(new { error = "Application not found", applicationNo });
        }

        // Authorization: owner or admin
        var userId = User.FindFirst("userId")?.Value;
        var isAdmin = User.IsInRole("Admin");
        
        if (!isAdmin && application.UserId != userId)
        {
            return NotFound(new { error = "Application not found", applicationNo });
        }

        // Fetch last run if exists
        LoanRun? lastRun = null;
        if (!string.IsNullOrEmpty(application.LastRunId))
        {
            lastRun = await _runRepo.GetLatestByApplicationAsync(applicationNo);
        }

        return Ok(new
        {
            application.ApplicationNo,
            application.UserId,
            application.ApplicationDate,
            application.Status,
            application.Applicant,
            application.LoanRequest,
            application.Financials,
            application.LastRunId,
            application.LastDecisionId,
            application.FundedLoanAccountId,
            lastRun = lastRun != null ? new
            {
                lastRun.RunId,
                lastRun.StartedAt,
                lastRun.CompletedAt,
                lastRun.DurationMs,
                lastRun.Recommendation,
                lastRun.WorkflowLog
            } : null
        });
    }

    /// <summary>
    /// GET /api/loans/applications — Admin-only list all applications.
    /// </summary>
    [HttpGet("applications")]
    [Authorize(Roles = "Admin")]
    public async Task<IActionResult> ListApplications([FromQuery] int pageSize = 50)
    {
        try
        {
            var applications = await _applicationRepo.GetAllAsync(pageSize);
            return Ok(applications);
        }
        catch (Exception ex)
        {
            var correlationId = HttpContext.TraceIdentifier;
            _logger.LogError(ex, "Failed to list applications. CorrelationId: {CorrelationId}", correlationId);
            return StatusCode(500, new { error = "An internal error occurred", correlationId });
        }
    }

    /// <summary>
    /// POST /api/loans/applications/{applicationNo}/run — Execute S01-S10 workflow synchronously.
    /// </summary>
    [HttpPost("applications/{applicationNo}/run")]
    [Authorize(Roles = "User,Admin")]
    public async Task<IActionResult> RunWorkflow(string applicationNo)
    {
        var application = await _applicationRepo.GetByIdAsync(applicationNo);
        if (application == null)
        {
            return NotFound(new { error = "Application not found", applicationNo });
        }

        // Authorization: owner or admin
        var userId = User.FindFirst("userId")?.Value;
        var isAdmin = User.IsInRole("Admin");
        
        if (!isAdmin && application.UserId != userId)
        {
            return NotFound(new { error = "Application not found", applicationNo });
        }

        try
        {
            _logger.LogInformation("Starting workflow run for application {ApplicationNo}", applicationNo);

            var response = await _orchestrator.RunWorkflowAsync(application);

            // Update application with last run ID and status
            application.LastRunId = response.RunId;
            application.Status = "recommended";
            await _applicationRepo.UpdateAsync(application);

            _logger.LogInformation("Completed workflow run {RunId} for application {ApplicationNo}, recommendation={Status}, confidence={Confidence}",
                response.RunId, applicationNo, response.Recommendation.Recommendation, response.Recommendation.Confidence);

            return Ok(response);
        }
        catch (Exception ex)
        {
            var correlationId = HttpContext.TraceIdentifier;
            _logger.LogError(ex, "Failed to run workflow for application {ApplicationNo}. CorrelationId: {CorrelationId}",
                applicationNo, correlationId);
            return StatusCode(500, new { error = "An internal error occurred", correlationId, details = ex.Message });
        }
    }

    private object? ValidateRequest(CreateLoanApplicationRequest request)
    {
        var errors = new List<object>();

        // Loan amount validation
        if (request.LoanRequest.Amount < 1000 || request.LoanRequest.Amount > 500000)
        {
            errors.Add(new { field = "loanRequest.amount", error = "Loan amount must be between $1,000 and $500,000" });
        }

        // Term validation
        if (!AllowedTerms.Contains(request.LoanRequest.TermMonths))
        {
            errors.Add(new { field = "loanRequest.termMonths", error = $"Term must be one of: {string.Join(", ", AllowedTerms)}" });
        }

        // Loan type validation
        if (!AllowedLoanTypes.Contains(request.LoanRequest.LoanType, StringComparer.OrdinalIgnoreCase))
        {
            errors.Add(new { field = "loanRequest.loanType", error = $"Loan type must be one of: {string.Join(", ", AllowedLoanTypes)}" });
        }

        // Email validation
        if (request.Applicant?.Email != null && !new EmailAddressAttribute().IsValid(request.Applicant.Email))
        {
            errors.Add(new { field = "applicant.email", error = "Invalid email address format" });
        }

        // Income validation
        if (request.Financials.GrossAnnualIncome < 0)
        {
            errors.Add(new { field = "financials.grossAnnualIncome", error = "Gross annual income cannot be negative" });
        }

        if (request.Financials.MonthlyNetIncome < 0)
        {
            errors.Add(new { field = "financials.monthlyNetIncome", error = "Monthly net income cannot be negative" });
        }

        if (errors.Count > 0)
        {
            return new { error = "Validation failed", details = errors };
        }

        return null;
    }
}

public class CreateLoanApplicationRequest
{
    public ApplicantInfo? Applicant { get; set; }
    
    [Required]
    public LoanRequestInfo LoanRequest { get; set; } = new();
    
    [Required]
    public FinancialInfo Financials { get; set; } = new();
}
