namespace LoanOrigination.Services;

/// <summary>
/// Generates unique application numbers in format APP-YYYY-NNNNNN.
/// Uses time-prefix + random suffix with collision retry (3 attempts).
/// </summary>
public class ApplicationNumberGenerator
{
    private readonly ILogger<ApplicationNumberGenerator> _logger;
    private static readonly Random _random = new();
    private static readonly object _lock = new();

    public ApplicationNumberGenerator(ILogger<ApplicationNumberGenerator> logger)
    {
        _logger = logger;
    }

    public string Generate()
    {
        int year = DateTime.UtcNow.Year;
        int sequence;
        
        lock (_lock)
        {
            // Generate 6-digit random sequence
            sequence = _random.Next(1, 999999);
        }

        var applicationNo = $"APP-{year}-{sequence:D6}";
        
        _logger.LogDebug("Generated application number: {ApplicationNo}", applicationNo);
        
        return applicationNo;
    }

    public async Task<string> GenerateUniqueAsync(Func<string, Task<bool>> existsCheck, int maxAttempts = 3)
    {
        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            var applicationNo = Generate();
            
            if (!await existsCheck(applicationNo))
            {
                return applicationNo;
            }
            
            _logger.LogWarning(
                "Application number {ApplicationNo} collision detected, attempt {Attempt}/{MaxAttempts}",
                applicationNo, attempt, maxAttempts);
        }

        throw new InvalidOperationException(
            $"Failed to generate unique application number after {maxAttempts} attempts");
    }
}
