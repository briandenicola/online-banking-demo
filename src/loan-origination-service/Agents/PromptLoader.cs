namespace LoanOrigination.Agents;

public class PromptLoader
{
    private readonly IWebHostEnvironment _environment;
    private readonly ILogger<PromptLoader> _logger;
    private readonly Dictionary<string, string> _prompts = new();

    public PromptLoader(IWebHostEnvironment environment, ILogger<PromptLoader> logger)
    {
        _environment = environment;
        _logger = logger;
    }

    public async Task LoadAllAsync()
    {
        var promptsPath = Path.Combine(_environment.ContentRootPath, "prompts");
        
        if (!Directory.Exists(promptsPath))
        {
            _logger.LogWarning("Prompts directory not found at {Path}", promptsPath);
            return;
        }

        var promptFiles = Directory.GetFiles(promptsPath, "*.txt");
        _logger.LogInformation("Loading {Count} prompt files from {Path}", promptFiles.Length, promptsPath);

        foreach (var file in promptFiles)
        {
            var name = Path.GetFileNameWithoutExtension(file);
            var content = await File.ReadAllTextAsync(file);
            _prompts[name] = content;
            _logger.LogDebug("Loaded prompt: {Name} ({Length} chars)", name, content.Length);
        }
    }

    public string GetPrompt(string name)
    {
        if (_prompts.TryGetValue(name, out var content))
        {
            return content;
        }

        _logger.LogWarning("Prompt {Name} not found", name);
        return string.Empty;
    }

    public bool HasPrompt(string name) => _prompts.ContainsKey(name);
}
