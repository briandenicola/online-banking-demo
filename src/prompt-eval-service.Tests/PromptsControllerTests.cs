using FluentAssertions;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using PromptEvalService.Controllers;
using PromptEvalService.Models;
using PromptEvalService.Services;
using Xunit;

namespace PromptEvalService.Tests;

public class PromptsControllerTests
{
    private readonly Mock<IPromptTemplateService> _templateServiceMock;
    private readonly Mock<ILogger<PromptsController>> _loggerMock;
    private readonly PromptsController _sut;

    public PromptsControllerTests()
    {
        _templateServiceMock = new Mock<IPromptTemplateService>();
        _loggerMock = new Mock<ILogger<PromptsController>>();
        _sut = new PromptsController(_templateServiceMock.Object, _loggerMock.Object);
    }

    [Fact]
    public async Task GetAll_ReturnsOkWithTemplates()
    {
        var templates = new List<PromptTemplate>
        {
            new() { Id = "t1", Name = "Template 1", Target = "risk-scoring", SystemPrompt = "Prompt 1" },
            new() { Id = "t2", Name = "Template 2", Target = "categorization", SystemPrompt = "Prompt 2" }
        };
        _templateServiceMock.Setup(s => s.GetAllAsync()).ReturnsAsync(templates);

        var result = await _sut.GetAll();

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var returnedTemplates = okResult.Value as List<PromptTemplate>;
        returnedTemplates.Should().HaveCount(2);
    }

    [Fact]
    public async Task GetById_ExistingTemplate_ReturnsOk()
    {
        var template = new PromptTemplate { Id = "t1", Name = "Test", Target = "risk-scoring", SystemPrompt = "Test prompt" };
        _templateServiceMock.Setup(s => s.GetByIdAsync("t1")).ReturnsAsync(template);

        var result = await _sut.GetById("t1");

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var returnedTemplate = okResult.Value as PromptTemplate;
        returnedTemplate!.Id.Should().Be("t1");
    }

    [Fact]
    public async Task GetById_NonExistentTemplate_ReturnsNotFound()
    {
        _templateServiceMock.Setup(s => s.GetByIdAsync("missing")).ReturnsAsync((PromptTemplate?)null);

        var result = await _sut.GetById("missing");

        result.Result.Should().BeOfType<NotFoundResult>();
    }

    [Fact]
    public async Task Create_ValidRequest_ReturnsCreatedAtAction()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "New Template",
            Target = "risk-scoring",
            SystemPrompt = "Analyze this transaction"
        };
        var created = new PromptTemplate { Id = "new-1", Name = "New Template", Target = "risk-scoring", SystemPrompt = "Analyze this transaction" };
        _templateServiceMock.Setup(s => s.CreateAsync(It.IsAny<PromptTemplate>())).ReturnsAsync(created);

        var result = await _sut.Create(request);

        var createdResult = result.Result.Should().BeOfType<CreatedAtActionResult>().Subject;
        var template = createdResult.Value as PromptTemplate;
        template!.Id.Should().Be("new-1");
    }

    [Fact]
    public async Task Create_EmptyName_ReturnsBadRequest()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "",
            Target = "risk-scoring",
            SystemPrompt = "Test prompt"
        };

        var result = await _sut.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task Create_EmptySystemPrompt_ReturnsBadRequest()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "Valid Name",
            Target = "risk-scoring",
            SystemPrompt = ""
        };

        var result = await _sut.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task Create_InvalidTarget_ReturnsBadRequest()
    {
        var request = new CreatePromptTemplateRequest
        {
            Name = "Valid Name",
            Target = "invalid-target",
            SystemPrompt = "Valid prompt"
        };

        var result = await _sut.Create(request);

        result.Result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task Update_ExistingTemplate_ReturnsOk()
    {
        var request = new UpdatePromptTemplateRequest { Name = "Updated Name" };
        var updated = new PromptTemplate { Id = "t1", Name = "Updated Name", Target = "risk-scoring", SystemPrompt = "Prompt" };
        _templateServiceMock.Setup(s => s.UpdateAsync("t1", request)).ReturnsAsync(updated);

        var result = await _sut.Update("t1", request);

        var okResult = result.Result.Should().BeOfType<OkObjectResult>().Subject;
        var template = okResult.Value as PromptTemplate;
        template!.Name.Should().Be("Updated Name");
    }

    [Fact]
    public async Task Update_NonExistentTemplate_ReturnsNotFound()
    {
        var request = new UpdatePromptTemplateRequest { Name = "Updated" };
        _templateServiceMock.Setup(s => s.UpdateAsync("missing", request)).ThrowsAsync(new KeyNotFoundException());

        var result = await _sut.Update("missing", request);

        result.Result.Should().BeOfType<NotFoundResult>();
    }

    [Fact]
    public async Task Delete_ExistingTemplate_ReturnsNoContent()
    {
        _templateServiceMock.Setup(s => s.DeleteAsync("t1")).Returns(Task.CompletedTask);

        var result = await _sut.Delete("t1");

        result.Should().BeOfType<NoContentResult>();
    }

    [Fact]
    public async Task Delete_NonExistentTemplate_ReturnsNotFound()
    {
        _templateServiceMock.Setup(s => s.DeleteAsync("missing"))
            .ThrowsAsync(new Microsoft.Azure.Cosmos.CosmosException("Not found", System.Net.HttpStatusCode.NotFound, 0, "", 0));

        var result = await _sut.Delete("missing");

        result.Should().BeOfType<NotFoundResult>();
    }
}
