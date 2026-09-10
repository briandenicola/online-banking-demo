using FluentAssertions;
using UserService.Models;
using UserService.Repositories;
using Xunit;

namespace UserService.Tests;

[Trait("Epic", "332")]
public class CustomerDirectoryRepositoryTests
{
    [Fact]
    public async Task Lookup_is_exact_match_first_before_prefix()
    {
        var repo = new InMemoryUserRepository();
        repo.Seed(new User { Id = "banker", Username = "banker", Email = "banker@example.com" });
        repo.Seed(new User { Id = "banker2", Username = "banker2", Email = "banker2@example.com" });

        var matches = await repo.LookupByUsernamePrefixAsync("banker", 5);

        matches.Should().ContainSingle();
        matches[0].Id.Should().Be("banker");
    }
}
