namespace PromptEvalService.Models;

// Request DTOs

public class CreatePromptTemplateRequest
{
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string Target { get; set; } = "risk-scoring";
    public string SystemPrompt { get; set; } = string.Empty;
}

public class UpdatePromptTemplateRequest
{
    public string? Name { get; set; }
    public string? Description { get; set; }
    public string? SystemPrompt { get; set; }
}

public class RunEvaluationRequest
{
    public string TemplateId { get; set; } = string.Empty;
    public List<string> TransactionIds { get; set; } = new();
}

// Response DTOs

public class EvaluationRunSummary
{
    public string Id { get; set; } = string.Empty;
    public string TemplateId { get; set; } = string.Empty;
    public string TemplateName { get; set; } = string.Empty;
    public int TemplateVersion { get; set; }
    public string Status { get; set; } = string.Empty;
    public int TransactionCount { get; set; }
    public QualityScores? QualityScores { get; set; }
    public SafetyScores? SafetyScores { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
}

public class PaginatedResponse<T>
{
    public List<T> Items { get; set; } = new();
    public int Total { get; set; }
    public int Page { get; set; }
    public int PageSize { get; set; }
}

public class ComparisonResponse
{
    public EvaluationRunSummary Run1 { get; set; } = new();
    public EvaluationRunSummary Run2 { get; set; } = new();
    public ScoreDeltas Deltas { get; set; } = new();
}

public class ScoreDeltas
{
    public double Coherence { get; set; }
    public double Fluency { get; set; }
    public double Relevance { get; set; }
    public double PassRate { get; set; }
}
