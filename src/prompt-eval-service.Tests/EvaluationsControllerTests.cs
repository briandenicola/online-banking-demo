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

public class EvaluationsControllerTests
{
    private readonly Mock<IEvaluationService> _evalServiceMock;
    private readonly Mock<ILogger<EvaluationsController>> _loggerMock;
    private readonly EvaluationsController _sut;

    public EvaluationsControllerTests()
    {
        _evalServiceMock = new Mock<IEvaluationService>();
        _loggerMock = new Mock<ILogger<EvaluationsController>>();
        _sut = new EvaluationsController(_evalServiceMock.Object, _loggerMock.Object);
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext()
        };
    }

    [Fact]
    public async Task RunEvaluation_ValidRequest_ReturnsAccepted()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "template-1",
            TransactionIds = new List<string> { "txn-1", "txn-2" }
        };
        var run = new EvaluationRun
        {
            Id = "run-1",
            TemplateId = "template-1",
            Status = "pending",
            TransactionCount = 2
        };
        _evalServiceMock.Setup(s => s.StartEvaluationAsync("template-1", request.TransactionIds)).ReturnsAsync(run);

        var result = await _sut.RunEvaluation(request);

        var acceptedResult = result.Result.Should().BeOfType<AcceptedAtActionResult>().Subject;
        var returnedRun = acceptedResult.Value as EvaluationRun;
        returnedRun!.Id.Should().Be("run-1");
    }

    [Fact]
    public async Task RunEvaluation_EmptyTemplateId_ReturnsBadRequest()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "",
            TransactionIds = new List<string> { "txn-1" }
        };

        var result = await _sut.RunEvaluation(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task RunEvaluation_EmptyTransactionIds_ReturnsBadRequest()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "template-1",
            TransactionIds = new List<string>()
        };

        var result = await _sut.RunEvaluation(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task RunEvaluation_TemplateNotFound_ReturnsNotFound()
    {
        var request = new RunEvaluationRequest
        {
            TemplateId = "missing-template",
            TransactionIds = new List<string> { "txn-1" }
        };
        _evalServiceMock.Setup(s => s.StartEvaluationAsync("missing-template", request.TransactionIds))
            .ThrowsAsync(new KeyNotFoundException());

        var result = await _sut.RunEvaluation(request);

        result.Result.Should().BeOfType<NotFoundObjectResult>();
    }

    [Fact]
    public async Task ListRuns_ReturnsOkWithPaginatedResponse()
    {
        var response = new PaginatedResponse<EvaluationRunSummary>
        {
            Items = new List<EvaluationRunSummary>
            {
                new() { Id = "run-1", TemplateId = "t1", Status = "completed" }
            },
            Total = 1,
            Page = 1,
            PageSize = 20
        };
        _evalServiceMock.Setup(s => s.ListRunsAsync(1, 20, null)).ReturnsAsync(response);

        var result = await _sut.ListRuns();

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var paginated = okResult.Value as PaginatedResponse<EvaluationRunSummary>;
        paginated!.Items.Should().HaveCount(1);
    }

    [Fact]
    public async Task GetRun_ExistingRun_ReturnsOk()
    {
        var run = new EvaluationRun { Id = "run-1", Status = "completed" };
        _evalServiceMock.Setup(s => s.GetRunAsync("run-1")).ReturnsAsync(run);

        var result = await _sut.GetRun("run-1");

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var returnedRun = okResult.Value as EvaluationRun;
        returnedRun!.Id.Should().Be("run-1");
    }

    [Fact]
    public async Task GetRun_NonExistentRun_ReturnsNotFound()
    {
        _evalServiceMock.Setup(s => s.GetRunAsync("missing")).ReturnsAsync((EvaluationRun?)null);

        var result = await _sut.GetRun("missing");

        result.Result.Should().BeOfType<NotFoundResult>();
    }

    [Fact]
    public async Task CompareRuns_ValidRuns_ReturnsOk()
    {
        var comparison = new ComparisonResponse
        {
            Run1 = new EvaluationRunSummary { Id = "run-1" },
            Run2 = new EvaluationRunSummary { Id = "run-2" },
            Deltas = new ScoreDeltas { Coherence = 0.1, Fluency = -0.05 }
        };
        _evalServiceMock.Setup(s => s.CompareRunsAsync("run-1", "run-2")).ReturnsAsync(comparison);

        var result = await _sut.CompareRuns("run-1", "run-2");

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var response = okResult.Value as ComparisonResponse;
        response!.Deltas.Coherence.Should().Be(0.1);
    }

    [Fact]
    public async Task CompareRuns_RunNotFound_ReturnsNotFound()
    {
        _evalServiceMock.Setup(s => s.CompareRunsAsync("run-1", "missing"))
            .ThrowsAsync(new KeyNotFoundException());

        var result = await _sut.CompareRuns("run-1", "missing");

        result.Result.Should().BeOfType<NotFoundObjectResult>();
    }
}
