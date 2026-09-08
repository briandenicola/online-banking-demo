using FluentAssertions;
using System.Text.RegularExpressions;
using Xunit;

namespace UserService.Tests;

/// <summary>
/// Binds the UserRegistered event producer to its only consumer.
///
/// The producer serialized a typed contract class into the payload's `data`
/// property, which emitted PascalCase (UserId/Username/Email). The Go consumer
/// reads camelCase. A Go map miss returns nil rather than an error, so the
/// consumer logged null for every field, ACKed the message, and reported
/// success. Nothing failed; the audit line was simply empty.
///
/// The two sides are written in different languages and neither imports the
/// other, so the only thing that can hold them together is a test that reads
/// both. That is what this does: it extracts the keys the consumer actually
/// looks up and asserts the producer emits each one.
/// </summary>
[Trait("Category", "Contract")]
public class EventPayloadCasingTests
{
    private static readonly string RepositoryRoot = FindRepositoryRoot();

    /// <summary>
    /// Walks up from the test assembly for a directory containing .git.
    /// Throws rather than returning null: a contract test that cannot find the
    /// files it is comparing must fail loudly, never pass vacuously.
    /// </summary>
    private static string FindRepositoryRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);

        while (dir is not null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, ".git")))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        throw new InvalidOperationException(
            $"Could not locate the repository root by walking up from {AppContext.BaseDirectory}. " +
            "This test compares the event producer against the Go consumer and cannot run without both.");
    }

    private static string ReadRepositoryFile(params string[] relativeSegments)
    {
        var path = Path.Combine(new[] { RepositoryRoot }.Concat(relativeSegments).ToArray());

        File.Exists(path).Should().BeTrue(
            $"the contract test needs {path}; if the file moved, update this test rather than deleting it");

        return File.ReadAllText(path);
    }

    /// <summary>
    /// Extracts the keys the Go consumer reads inside its `case "UserRegistered":` block.
    /// </summary>
    private static IReadOnlyList<string> ConsumerKeysForUserRegistered()
    {
        var consumer = ReadRepositoryFile("src", "event-processor", "main.go");

        var caseStart = consumer.IndexOf("case \"UserRegistered\":", StringComparison.Ordinal);
        caseStart.Should().BeGreaterThan(-1,
            "the consumer must still handle UserRegistered; if the case was removed the producer should go too");

        // Bounded by the next `case ` label so we only capture this event's keys.
        var nextCase = consumer.IndexOf("\tcase ", caseStart + 1, StringComparison.Ordinal);
        var block = nextCase > caseStart
            ? consumer[caseStart..nextCase]
            : consumer[caseStart..];

        var keys = Regex.Matches(block, @"evt\.Data\[""(?<key>[A-Za-z0-9_]+)""\]")
            .Select(m => m.Groups["key"].Value)
            .Distinct()
            .ToList();

        keys.Should().NotBeEmpty("the consumer reads named fields off the UserRegistered payload");

        return keys;
    }

    private static string UserRegisteredPublishMethod()
    {
        var producer = ReadRepositoryFile("src", "user-service", "Services", "UserService.cs");

        var methodStart = producer.IndexOf("PublishUserRegisteredEvent(UserModel user)", StringComparison.Ordinal);
        methodStart.Should().BeGreaterThan(-1, "the producer method must still exist");

        var next = producer.IndexOf("private async Task Publish", methodStart + 1, StringComparison.Ordinal);
        return next > methodStart ? producer[methodStart..next] : producer[methodStart..];
    }

    [Fact]
    public void UserRegisteredPayload_EmitsEveryKeyTheConsumerReads()
    {
        var method = UserRegisteredPublishMethod();

        foreach (var key in ConsumerKeysForUserRegistered())
        {
            method.Should().Contain($"{key} =",
                $"event-processor reads evt.Data[\"{key}\"] off the UserRegistered payload. " +
                "If the producer does not emit that exact key, the consumer logs null for it and ACKs " +
                "without error — the audit entry is silently blank rather than failing.");
        }
    }

    [Fact]
    public void UserRegisteredPayload_DoesNotSerializeATypedContractIntoData()
    {
        var method = UserRegisteredPublishMethod();

        // The regression: `data = evt` serialized UserRegisteredEvent's PascalCase
        // properties. Every sibling event on this stream builds `data` inline in
        // camelCase, which is what the consumer expects.
        method.Should().NotMatchRegex(@"data\s*=\s*evt\b",
            "assigning a typed contract to `data` serializes PascalCase property names, " +
            "which the camelCase-reading consumer cannot see. Build the payload inline like the sibling events.");
    }
}
