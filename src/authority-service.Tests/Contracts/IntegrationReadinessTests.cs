using System.Text.Json;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Contracts;

/// <summary>
/// THE ANTI-VACUOUS-PASS MECHANISM FOR THE WHOLE PROJECT.
///
/// Much of this suite was written before the code it tests existed. The normal way to express
/// that is <c>[Fact(Skip = "waiting for Turk")]</c> — and a skipped test is the most dangerous
/// artefact in a repository. It is invisible in a green run, it stays skipped after the blocker
/// clears, and six months later nobody remembers whether it was skipped because the code was
/// missing or because it was failing.
///
/// So instead: every blocked dependency is enumerated in pending-integration.manifest.json with
/// an honest claim about whether it exists yet. The tests below RUN, every time, and FAIL when a
/// claim stops being true. When Turk's service lands, this file goes red and says so — which is
/// the only reliable way to make a pending test get wired up.
///
/// A red build here is never "the code is broken". It is "a test that was waiting for you is now
/// able to run."
/// </summary>
public sealed class IntegrationReadinessTests(ITestOutputHelper output)
{
    private static readonly string RepoRoot = FindRepoRoot();

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, ".git")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Repository root not found.");
    }

    private sealed record Dependency(
        string Id, string Path, string Owner, string Status,
        string? Marker, string[] Blocks, string[] Covers)
    {
        public bool ExpectedAbsent => Status == "pending";
        public bool Landed => Status == "landed";
    }

    private static List<Dependency> Manifest()
    {
        var file = System.IO.Path.Combine(AppContext.BaseDirectory, "pending-integration.manifest.json");
        File.Exists(file).Should().BeTrue("the manifest is copied to the output directory");

        using var doc = JsonDocument.Parse(File.ReadAllText(file));

        return doc.RootElement.GetProperty("dependencies").EnumerateArray()
            .Select(d => new Dependency(
                d.GetProperty("id").GetString()!,
                d.GetProperty("path").GetString()!,
                d.GetProperty("owner").GetString()!,
                d.GetProperty("status").GetString()!,
                d.TryGetProperty("marker", out var c) ? c.GetString() : null,
                d.GetProperty("blocks").EnumerateArray().Select(b => b.GetString()!).ToArray(),
                d.TryGetProperty("covers", out var cv)
                    ? cv.EnumerateArray().Select(b => b.GetString()!).ToArray()
                    : []))
            .ToList();
    }

    [Fact]
    public void The_manifest_is_non_empty_and_well_formed()
    {
        var deps = Manifest();

        deps.Should().NotBeEmpty();
        deps.Should().OnlyContain(d => d.Status == "pending" || d.Status == "landed",
            "status drives enforcement in both directions; an unrecognised value would silently " +
            "enforce nothing");
        deps.Should().OnlyContain(d => d.Blocks.Length > 0 || d.Covers.Length > 0,
            "a dependency that neither blocks nor covers anything does not belong in the ledger");
        deps.Select(d => d.Id).Should().OnlyHaveUniqueItems();
    }

    [Fact]
    public void No_dependency_marked_absent_has_quietly_appeared()
    {
        var appeared = new List<Dependency>();

        foreach (var dep in Manifest().Where(d => d.ExpectedAbsent))
        {
            var full = Path.Combine(RepoRoot, dep.Path);
            if (File.Exists(full) || Directory.Exists(full)) appeared.Add(dep);
        }

        foreach (var dep in appeared)
        {
            output.WriteLine($"NOW AVAILABLE: {dep.Path} (owner: {dep.Owner})");
            foreach (var b in dep.Blocks) output.WriteLine($"    unblocks: {b}");
        }

        appeared.Should().BeEmpty(
            "these dependencies now exist, so the tests waiting on them can be wired up. " +
            "Set expectedAbsent=false in the manifest IN THE SAME CHANGE that connects them — " +
            "not before, or the ledger starts lying in the other direction.");
    }

    [Fact]
    public void Every_landed_dependency_still_exists_and_still_carries_its_marker()
    {
        // Once a dependency lands, the SAME ledger entry flips from a tripwire into a regression
        // guard. This is the direction people forget: the day someone deletes the audit case for
        // ApprovalVoidedByPolicyChange, or renames the gateway route, no other test in this repo
        // would notice.
        foreach (var dep in Manifest().Where(d => d.Landed))
        {
            var full = Path.Combine(RepoRoot, dep.Path);

            (File.Exists(full) || Directory.Exists(full)).Should().BeTrue(
                $"'{dep.Id}' is recorded as landed but {dep.Path} is gone (owner: {dep.Owner})");

            if (dep.Marker is null || !File.Exists(full)) continue;

            File.ReadAllText(full).Should().Contain(dep.Marker,
                $"'{dep.Id}' has lost its authority wiring marker '{dep.Marker}'");
        }
    }

    [Fact]
    public void Every_dependency_expected_to_exist_actually_does()
    {
        // The other direction, and it matters just as much. A manifest entry pointing at a file
        // that was renamed or deleted silently stops guarding anything.
        var missing = Manifest()
            .Where(d => d.Landed)
            .Where(d => !File.Exists(Path.Combine(RepoRoot, d.Path))
                        && !Directory.Exists(Path.Combine(RepoRoot, d.Path)))
            .ToList();

        missing.Should().BeEmpty(
            "the manifest claims these exist; if one was moved, update the path rather than " +
            "letting the entry rot");
    }

    [Fact]
    public void No_pending_dependency_has_quietly_acquired_its_wiring()
    {
        // Content, not just existence. A file can be present for years and only later gain the
        // Banker Copilot wiring; that moment is when the tests it blocks become writable.
        var ready = new List<(Dependency Dep, string Marker)>();

        foreach (var dep in Manifest().Where(d => d.ExpectedAbsent && d.Marker is not null))
        {
            var full = Path.Combine(RepoRoot, dep.Path);
            if (!File.Exists(full)) continue;

            if (File.ReadAllText(full).Contains(dep.Marker!, StringComparison.Ordinal))
                ready.Add((dep, dep.Marker!));
        }

        foreach (var (dep, marker) in ready)
        {
            output.WriteLine($"NOW WIRED: {dep.Path} contains '{marker}' (owner: {dep.Owner})");
            foreach (var b in dep.Blocks) output.WriteLine($"    unblocks: {b}");
        }

        ready.Should().BeEmpty(
            "the authority wiring has landed in these files; flip the entry to status='landed' " +
            "and wire up the tests it was blocking");
    }

    [Fact]
    public void The_ledger_reports_itself_so_the_status_is_never_guesswork()
    {
        // Not an assertion so much as a printed status line. "What actually runs versus what is
        // written-but-pending" should be answerable from a test run, not from someone's memory
        // of a stand-up.
        var deps = Manifest();
        var blocked = deps.Sum(d => d.Blocks.Length);
        var covered = deps.Sum(d => d.Covers.Length);

        output.WriteLine($"Phase 1 integration ledger: {deps.Count} dependencies, " +
                         $"{covered} test areas COVERED, {blocked} still PENDING.");

        foreach (var dep in deps.OrderBy(d => d.Owner, StringComparer.Ordinal))
        {
            output.WriteLine($"  [{dep.Status,-7}] {dep.Path} ({dep.Owner}) " +
                             $"— {dep.Covers.Length} covered, {dep.Blocks.Length} pending");
            foreach (var b in dep.Blocks) output.WriteLine($"        PENDING: {b}");
        }

        blocked.Should().BeGreaterThan(0,
            "if this ever reaches zero, delete the manifest and this file rather than leaving an " +
            "empty ledger that looks like coverage");
    }

    [Fact]
    public void Both_owners_are_represented_so_neither_half_is_forgotten()
    {
        var owners = Manifest().Select(d => d.Owner).Distinct().ToList();

        owners.Should().Contain("Turk", "the policy engine and store");
        owners.Should().Contain("Rusty", "infra, roles, audit cases and the gateway route");
    }
}
