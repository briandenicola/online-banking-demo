using System;
using System.Collections.Generic;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace UserService.Services;

public class AuthService : IAuthService
{
    private readonly IConfiguration _configuration;
    private readonly IRoleHierarchy _roleHierarchy;

    public AuthService(IConfiguration configuration)
        : this(configuration, RoleHierarchy.Default)
    {
    }

    public AuthService(IConfiguration configuration, IRoleHierarchy roleHierarchy)
    {
        _configuration = configuration;
        _roleHierarchy = roleHierarchy;
    }

    public async Task<string> GenerateTokenAsync(string userId, string username, string role)
    {
        var key = Encoding.UTF8.GetBytes(_configuration["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key is not configured"));
        var expiresInMinutes = int.Parse(_configuration["Jwt:ExpiresInMinutes"] ?? throw new InvalidOperationException("Jwt:ExpiresInMinutes is not configured"));

        // Expand the flat role ONCE, here, per epic #332 §5.8.2. The flat `role`
        // claim is retained unchanged for ADR-003 compatibility.
        var effectiveRoles = _roleHierarchy.Expand(role);

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, userId),
            new(JwtRegisteredClaimNames.UniqueName, username),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new("userId", userId),
            new(ClaimTypes.Role, role)
        };

        foreach (var effectiveRole in effectiveRoles)
        {
            claims.Add(new Claim(Constants.ClaimNames.EffectiveRoles, effectiveRole));

            // Also emit the implied roles as role claims so that existing
            // [Authorize(Roles = ...)] guards see the expansion without every
            // controller in the repo having to learn about effectiveRoles.
            // The declared role is already present above; skip the duplicate.
            if (!string.Equals(effectiveRole, role, StringComparison.OrdinalIgnoreCase))
            {
                claims.Add(new Claim(ClaimTypes.Role, effectiveRole));
            }
        }

        claims.Add(new Claim(
            Constants.ClaimNames.Seniority,
            _roleHierarchy.SeniorityOf(role).ToString(System.Globalization.CultureInfo.InvariantCulture)));

        var tokenDescriptor = new SecurityTokenDescriptor
        {
            Subject = new ClaimsIdentity(claims),
            Expires = DateTime.UtcNow.AddMinutes(expiresInMinutes),
            Issuer = _configuration["Jwt:Issuer"],
            Audience = _configuration["Jwt:Audience"],
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(key),
                SecurityAlgorithms.HmacSha256Signature)
        };

        var tokenHandler = new JwtSecurityTokenHandler();
        var token = tokenHandler.CreateToken(tokenDescriptor);
        return await Task.FromResult(tokenHandler.WriteToken(token));
    }

    public async Task<bool> ValidateTokenAsync(string token)
    {
        var tokenHandler = new JwtSecurityTokenHandler();
        var key = Encoding.UTF8.GetBytes(_configuration["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key is not configured"));

        try
        {
            tokenHandler.ValidateToken(token, new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidateAudience = true,
                ValidateLifetime = true,
                ValidateIssuerSigningKey = true,
                ValidIssuer = _configuration["Jwt:Issuer"],
                ValidAudience = _configuration["Jwt:Audience"],
                IssuerSigningKey = new SymmetricSecurityKey(key)
            }, out _);

            return await Task.FromResult(true);
        }
        catch
        {
            return await Task.FromResult(false);
        }
    }
}