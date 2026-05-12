using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using PromptEvalService.Controllers;
using PromptEvalService.Models;
using PromptEvalService.Services;
using Xunit;

namespace PromptEvalService.Tests;

/// <summary>
/// Security tests for the prompt-eval-service.
/// Covers: error information leakage, input validation edge cases.
/// </summary>
[Trait("Category", "Security")]
public class SecurityTests
{
    private readonly Mock<IEvaluationService> _evalServiceMock;
    private readonly Mock<ILogger<EvaluationsController>> _evalLoggerMock;
    private readonly EvaluationsController _evalController;

    private readonly Mock<IPromptTemplateService> _templateServiceMock;
    private readonly Mock<ILogger<PromptsController>> _promptsLoggerMock;
    private readonly PromptsController _promptsController;

    public SecurityTests()
    {
        _evalServiceMock = new Mock<IEvaluationService>();
        _evalLoggerMock = new Mock<ILogger<EvaluationsController>>();
        _evalController = new EvaluationsController(_evalServiceMock.Object, _evalLoggerMock.Object);
        _evalController.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext()
        };

        _templateServiceMock = new Mock<IPromptTemplateService>();
        _promptsLoggerMock = new Mock<ILogger<PromptsController>>();
        _promptsController = new PromptsController(_templateServiceMock.Object, _promptsLoggerMock.Object);
    }

    /// <summary>
    /// SECURITY: When an internal exception occurs during evaluation, the error
    /// response must not leak stack traces or internal details. Only a correlation
    /// ID and generic message should be returned.
    /// </summary>
    [Fact]
    public async Task RunEvaluation_InternalError_DoesNotLeakStackTrace()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "template-1",
            TransactionIds = new List<string> { "txn-1" }
        };
        _evalServiceMock.Setup(s => s.StartEvaluationAsync("template-1", request.TransactionIds))
            .ThrowsAsync(new InvalidOperationException("Cosmos DB connection refused at 10.0.0.5:443"));

        var result = await _evalController.RunEvaluation(request);

        var statusResult = result.Result.Should().BeOfType<ObjectResult>().Subject;
        statusResult.StatusCode.Should().Be(500);

        var errorBody = statusResult.Value;
        var errorJson = System.Text.Json.JsonSerializer.Serialize(errorBody);

        // Must not contain internal details
        errorJson.Should().NotContain("Cosmos DB");
        errorJson.Should().NotContain("10.0.0.5");
        errorJson.Should().NotContain("connection refused", because: "internal error details must not leak to clients");

        // Should contain a correlation ID for debugging
        errorJson.Should().Contain("correlationId");
    }

    /// <summary>
    /// SECURITY: CompareRuns internal errors must not leak details either.
    /// </summary>
    [Fact]
    public async Task CompareRuns_InternalError_DoesNotLeakStackTrace()
    {
        _evalServiceMock.Setup(s => s.CompareRunsAsync("run-1", "run-2"))
            .ThrowsAsync(new Exception("NullReferenceException at EvaluationService.cs:142"));

        var result = await _evalController.CompareRuns("run-1", "run-2");

        var statusResult = result.Result.Should().BeOfType<ObjectResult>().Subject;
        statusResult.StatusCode.Should().Be(500);

        var errorJson = System.Text.Json.JsonSerializer.Serialize(statusResult.Value);
        errorJson.Should().NotContain("NullReferenceException");
        errorJson.Should().NotContain("EvaluationService.cs");
        errorJson.Should().Contain("correlationId");
    }

    /// <summary>
    /// SECURITY: Input validation — whitespace-only templateId must be rejected.
    /// </summary>
    [Fact]
    public async Task RunEvaluation_WhitespaceTemplateId_ReturnsBadRequest()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "   ",
            TransactionIds = new List<string> { "txn-1" }
        };

        var result = await _evalController.RunEvaluation(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// SECURITY: Input validation — prompt template name with only whitespace must be rejected.
    /// </summary>
    [Fact]
    public async Task CreateTemplate_WhitespaceName_ReturnsBadRequest()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "   ",
            Target = "risk-scoring",
            SystemPrompt = "Valid prompt"
        };

        var result = await _promptsController.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// SECURITY: Input validation — systemPrompt with only whitespace must be rejected.
    /// </summary>
    [Fact]
    public async Task CreateTemplate_WhitespaceSystemPrompt_ReturnsBadRequest()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "Valid Name",
            Target = "risk-scoring",
            SystemPrompt = "   "
        };

        var result = await _promptsController.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// SECURITY: Only 'risk-scoring' and 'categorization' are valid targets.
    /// Arbitrary strings must be rejected.
    /// </summary>
    [Theory]
    [InlineData("")]
    [InlineData("malicious")]
    [InlineData("admin")]
    [InlineData("risk-scoring; DROP TABLE")]
    public async Task CreateTemplate_InvalidTarget_ReturnsBadRequest(string target)
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "Valid Name",
            Target = target,
            SystemPrompt = "Valid prompt"
        };

        var result = await _promptsController.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// SECURITY: Valid targets must be accepted.
    /// </summary>
    [Theory]
    [InlineData("risk-scoring")]
    [InlineData("categorization")]
    public async Task CreateTemplate_ValidTarget_Succeeds(string target)
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "Valid Name",
            Target = target,
            SystemPrompt = "Valid prompt text"
        };
        _templateServiceMock.Setup(s => s.CreateAsync(It.IsAny<PromptTemplate>()))
            .ReturnsAsync(new PromptTemplate { Id = "t1", Name = request.Name, Target = target, SystemPrompt = request.SystemPrompt });

        var result = await _promptsController.Create(request);

        result.Result.Should().BeOfType<CreatedAtActionResult>();
    }
}
