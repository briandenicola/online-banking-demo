using Newtonsoft.Json;

namespace PromptEvalService.Models;

public class EvaluationRun
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    [JsonProperty("templateId")]
    public string TemplateId { get; set; } = string.Empty;

    [JsonProperty("templateName")]
    public string TemplateName { get; set; } = string.Empty;

    [JsonProperty("templateVersion")]
    public int TemplateVersion { get; set; }

    [JsonProperty("foundryEvalId")]
    public string? FoundryEvalId { get; set; }

    [JsonProperty("foundryRunId")]
    public string? FoundryRunId { get; set; }

    [JsonProperty("status")]
    public string Status { get; set; } = "pending"; // pending, running, completed, failed

    [JsonProperty("transactionCount")]
    public int TransactionCount { get; set; }

    [JsonProperty("userId")]
    public string UserId { get; set; } = "global";

    [JsonProperty("qualityScores")]
    public QualityScores? QualityScores { get; set; }

    [JsonProperty("safetyScores")]
    public SafetyScores? SafetyScores { get; set; }

    [JsonProperty("outputItems")]
    public List<EvaluationOutputItem>? OutputItems { get; set; }

    [JsonProperty("error")]
    public string? Error { get; set; }

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    [JsonProperty("completedAt")]
    public DateTime? CompletedAt { get; set; }
}

public class QualityScores
{
    [JsonProperty("coherence")]
    public double Coherence { get; set; }

    [JsonProperty("fluency")]
    public double Fluency { get; set; }

    [JsonProperty("relevance")]
    public double Relevance { get; set; }

    [JsonProperty("passRate")]
    public double PassRate { get; set; }
}

public class SafetyScores
{
    [JsonProperty("violence")]
    public SafetyResult Violence { get; set; } = new();

    [JsonProperty("hateUnfairness")]
    public SafetyResult HateUnfairness { get; set; } = new();

    [JsonProperty("selfHarm")]
    public SafetyResult SelfHarm { get; set; } = new();

    [JsonProperty("sexual")]
    public SafetyResult Sexual { get; set; } = new();
}

public class SafetyResult
{
    [JsonProperty("passed")]
    public bool Passed { get; set; } = true;

    [JsonProperty("averageScore")]
    public double AverageScore { get; set; }

    [JsonProperty("failedCount")]
    public int FailedCount { get; set; }
}

public class EvaluationOutputItem
{
    [JsonProperty("transactionId")]
    public string TransactionId { get; set; } = string.Empty;

    [JsonProperty("query")]
    public string Query { get; set; } = string.Empty;

    [JsonProperty("response")]
    public string Response { get; set; } = string.Empty;

    [JsonProperty("queryMessages")]
    public List<object>? QueryMessages { get; set; }

    [JsonProperty("responseMessages")]
    public List<object>? ResponseMessages { get; set; }

    [JsonProperty("scores")]
    public Dictionary<string, object>? Scores { get; set; }

    [JsonProperty("status")]
    public string Status { get; set; } = string.Empty;

    [JsonProperty("coherenceScore")]
    public double CoherenceScore { get; set; }

    [JsonProperty("fluencyScore")]
    public double FluencyScore { get; set; }

    [JsonProperty("relevanceScore")]
    public double RelevanceScore { get; set; }

    [JsonProperty("safetyPassed")]
    public bool SafetyPassed { get; set; } = true;

    [JsonProperty("safetyDetails")]
    public Dictionary<string, double> SafetyDetails { get; set; } = new();

    [JsonProperty("adminDecision")]
    public string? AdminDecision { get; set; }

    [JsonProperty("adminNotes")]
    public string? AdminNotes { get; set; }

    [JsonProperty("reviewedBy")]
    public string? ReviewedBy { get; set; }

    [JsonProperty("reviewedAt")]
    public DateTime? ReviewedAt { get; set; }
}
