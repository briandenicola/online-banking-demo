using FluentAssertions;
using Moq;
using PromptEvalService.Controllers;
using PromptEvalService.Models;
using PromptEvalService.Repositories;
using PromptEvalService.Services;
using Xunit;

namespace PromptEvalService.Tests;

public class TrajectoryScorerTests
{
    private static string ResolveRepositoryRoot()
    {
        var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (directory != null)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "trajectories");
            if (Directory.Exists(candidate))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        return Directory.GetCurrentDirectory();
    }

    private static string FixtureRoot => Path.Combine(ResolveRepositoryRoot(), "tests", "fixtures", "trajectories");

    private static string TracePath(string scenario) => Path.Combine(FixtureRoot, scenario, "trace.json");
    private static string ExpectedPath(string scenario) => Path.Combine(FixtureRoot, scenario, "expected.json");

    [Fact]
    public async Task ToolSelectionScorer_AcceptsExpectedSequence()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("flagged-transaction-l1-resolution"), ExpectedPath("flagged-transaction-l1-resolution"));

        var result = record.Results.Single(r => r.ScorerName == "ToolSelection");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
    }

    [Theory]
    [InlineData("flagged-transaction-l1-resolution", "L1")]
    [InlineData("flagged-transaction-l2-escalation", "L2")]
    public async Task EscalationCorrectness_ComparesRungToFixture(string scenario, string expectedRung)
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath(scenario), ExpectedPath(scenario));

        var result = record.Results.Single(r => r.ScorerName == "EscalationCorrectness");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
        result.Actual["predictedRung"].Should().Be(expectedRung);
    }

    [Fact]
    public async Task EvidenceCompleteness_SatisfiesRequiredEvidenceSet()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("flagged-transaction-l1-resolution"), ExpectedPath("flagged-transaction-l1-resolution"));

        var result = record.Results.Single(r => r.ScorerName == "EvidenceCompleteness");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
    }

    [Fact]
    public async Task RecommendationQuality_UsesGroundTruthRecommendation()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("flagged-transaction-l2-escalation"), ExpectedPath("flagged-transaction-l2-escalation"));

        var result = record.Results.Single(r => r.ScorerName == "RecommendationQuality");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
        result.Actual["recommendation"].Should().Be("escalate");
    }

    [Fact]
    public async Task SupervisorIndependence_AllowsIndependentSecondOpinionWithoutReuse()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("supervisor-fanout-multiple-parallel-calls"), ExpectedPath("supervisor-fanout-multiple-parallel-calls"));

        var result = record.Results.Single(r => r.ScorerName == "SupervisorIndependence");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
    }

    [Fact]
    public async Task FanOutEfficiency_ReportsModelUsageWithoutTelemetryAsDegraded()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("flagged-transaction-l1-resolution"), ExpectedPath("flagged-transaction-l1-resolution"));

        var result = record.Results.Single(r => r.ScorerName == "FanOutEfficiency");
        result.Status.Should().Be(TrajectoryScoreStatus.Degraded);
        result.Details["modelCallCount"].Should().Be(0);
    }

    [Fact]
    public async Task InjectionResistance_RejectsUnsafePromptingButPreservesSafeExecution()
    {
        var scorer = new TrajectoryScorer();
        var record = await scorer.ScoreFixtureAsync(TracePath("adversarial-prompt-injection-resistance"), ExpectedPath("adversarial-prompt-injection-resistance"));

        var result = record.Results.Single(r => r.ScorerName == "InjectionResistance");
        result.Status.Should().Be(TrajectoryScoreStatus.Pass);
    }

    [Fact]
    public async Task RunningFixtureDirectory_PersistsExpectedAndPredictedRungsForEveryRealFixture()
    {
        var persistedRecords = new List<TrajectoryEvaluationRecord>();
        var repository = new Mock<ITrajectoryEvaluationRepository>();
        repository
            .Setup(r => r.CreateAsync(It.IsAny<TrajectoryEvaluationRecord>()))
            .ReturnsAsync((TrajectoryEvaluationRecord record) =>
            {
                persistedRecords.Add(record);
                return record;
            });

        var scorer = new TrajectoryScorer(repository: repository.Object);
        var controller = new TrajectoryEvalController(scorer, repository.Object);
        await controller.RunTrajectoryEvaluation(new RunTrajectoryEvaluationRequest { FixtureRoot = FixtureRoot });

        persistedRecords.Should().HaveCount(5);
        persistedRecords.Should().OnlyContain(record =>
            !string.IsNullOrWhiteSpace(record.ExpectedEscalationRung) &&
            !string.IsNullOrWhiteSpace(record.PredictedEscalationRung));
        persistedRecords.Single(r => r.Scenario == "flagged-transaction-l1-resolution")
            .Should().Match<TrajectoryEvaluationRecord>(r => r.ExpectedEscalationRung == "L1" && r.PredictedEscalationRung == "L1");
        persistedRecords.Single(r => r.Scenario == "flagged-transaction-l2-escalation")
            .Should().Match<TrajectoryEvaluationRecord>(r => r.ExpectedEscalationRung == "L2" && r.PredictedEscalationRung == "L2");
    }
}
