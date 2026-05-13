using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Dtos;

/// <summary>
/// User registration request
/// </summary>
public class RegisterUserRequest
{
    [Required]
    [StringLength(50, MinimumLength = 3)]
    [RegularExpression("^[a-zA-Z0-9_.-]+$",
        ErrorMessage = "Username may only contain letters, digits, underscore, dot, or hyphen.")]
    public string Username { get; set; } = null!;

    [Required]
    [EmailAddress]
    [StringLength(255)]
    public string Email { get; set; } = null!;

    [Required]
    [StringLength(128, MinimumLength = 8)]
    public string Password { get; set; } = null!;

    [Required]
    [StringLength(100, MinimumLength = 1)]
    public string FirstName { get; set; } = null!;

    [Required]
    [StringLength(100, MinimumLength = 1)]
    public string LastName { get; set; } = null!;
}