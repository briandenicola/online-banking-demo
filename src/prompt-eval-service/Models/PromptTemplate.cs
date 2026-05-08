using Newtonsoft.Json;

namespace PromptEvalService.Models;

public class PromptTemplate
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    [JsonProperty("name")]
    public string Name { get; set; } = string.Empty;

    [JsonProperty("description")]
    public string? Description { get; set; }

    [JsonProperty("target")]
    public string Target { get; set; } = "risk-scoring"; // "risk-scoring" or "categorization"

    [JsonProperty("systemPrompt")]
    public string SystemPrompt { get; set; } = string.Empty;

    [JsonProperty("version")]
    public int Version { get; set; } = 1;

    [JsonProperty("userId")]
    public string UserId { get; set; } = "global";

    [JsonProperty("isActive")]
    public bool IsActive { get; set; }

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    [JsonProperty("updatedAt")]
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
