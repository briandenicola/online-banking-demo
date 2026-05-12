using System.ComponentModel.DataAnnotations;

namespace PromptEvalService.Models;

// Request DTOs

public class CreatePromptTemplateRequest
{
    [Required]
    [StringLength(200, MinimumLength = 1)]
    public string Name { get; set; } = string.Empty;

    [StringLength(1000)]
    public string? Description { get; set; }

    [Required]
    [RegularExpression("^(risk-scoring|categorization)$", ErrorMessage = "Target must be 'risk-scoring' or 'categorization'")]
    public string Target { get; set; } = "risk-scoring";

    [Required]
    [StringLength(10000, MinimumLength = 1)]
    public string SystemPrompt { get; set; } = string.Empty;
}

public class UpdatePromptTemplateRequest
{
    [StringLength(200, MinimumLength = 1)]
    public string? Name { get; set; }

    [StringLength(1000)]
    public string? Description { get; set; }

    [StringLength(10000, MinimumLength = 1)]
    public string? SystemPrompt { get; set; }
}

public class RunEvaluationRequest
{
    [Required]
    [StringLength(128)]
    public string TemplateId { get; set; } = string.Empty;

    [Required]
    [MinLength(1, ErrorMessage = "At least one transaction ID is required")]
    [MaxLength(100)]
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
