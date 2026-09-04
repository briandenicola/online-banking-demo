using FluentAssertions;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Xunit;

namespace UserService.Tests;

/// <summary>
/// Security tests for Issue #35: Cosmos SDK Stabilized.
/// Verifies all .NET projects use stable Cosmos SDK versions (no pre-release).
/// </summary>
[Trait("Category", "Security")]
[Trait("Issue", "35")]
public class CosmosSDKVersionTests
{
    private const string DirectoryPackagesPath = "Directory.Packages.props";

    /// <summary>
    /// Repository root, discovered by walking up from the test assembly until a
    /// directory containing BOTH .git and Directory.Packages.props is found.
    ///
    /// This was previously a hardcoded absolute path, which meant these security
    /// tests only ran on one machine. Everywhere else they either failed outright
    /// or — worse — passed vacuously, because the file-not-found branch returned
    /// success. A security test that cannot find what it is auditing must FAIL,
    /// never silently pass, so discovery throws rather than returning null.
    /// </summary>
    private static readonly string RepositoryRoot = FindRepositoryRoot();

    private static string FindRepositoryRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);

        while (dir is not null)
        {
            var hasGit = Directory.Exists(Path.Combine(dir.FullName, ".git"))
                         || File.Exists(Path.Combine(dir.FullName, ".git"));
            var hasPackages = File.Exists(Path.Combine(dir.FullName, DirectoryPackagesPath));

            if (hasGit && hasPackages)
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        throw new InvalidOperationException(
            $"Could not locate the repository root above '{AppContext.BaseDirectory}'. " +
            $"Expected an ancestor directory containing both '.git' and '{DirectoryPackagesPath}'. " +
            "These Issue #35 security tests audit real repository files and must not be " +
            "reported as passing when those files cannot be found.");
    }

    /// <summary>
    /// SECURITY (Issue #35): Verifies Directory.Packages.props uses stable Cosmos SDK version.
    /// Pre-release 3.59.0-preview.0 should be replaced with stable 3.58.0.
    /// </summary>
    [Fact]
    public void DirectoryPackages_CosmosSDK_IsStableVersion()
    {
        var packagesPath = Path.Combine(RepositoryRoot, DirectoryPackagesPath);

        // Deliberately NOT a silent return. The original code treated a missing
        // Directory.Packages.props as "skip", which reported this security test as
        // PASSING on every machine that could not find the file. Absence of the
        // audited artifact is a failure condition, not a pass.
        File.Exists(packagesPath).Should().BeTrue(
            $"the Cosmos SDK version audit requires '{packagesPath}'; if central package " +
            "management were genuinely removed this test must fail loudly rather than pass silently");

        var content = File.ReadAllText(packagesPath);
        var doc = XDocument.Parse(content);

        var cosmosPackage = doc.Descendants("PackageVersion")
            .FirstOrDefault(e => e.Attribute("Include")?.Value == "Microsoft.Azure.Cosmos");

        cosmosPackage.Should().NotBeNull("Microsoft.Azure.Cosmos package should be defined");
        
        var version = cosmosPackage!.Attribute("Version")?.Value;
        version.Should().NotBeNull("Cosmos SDK version should be specified");

        // Verify version does NOT contain pre-release markers
        version!.Should().NotContain("preview", "Should not use preview versions");
        version.Should().NotContain("rc", "Should not use release candidate versions");
        version.Should().NotContain("beta", "Should not use beta versions");
        version.Should().NotContain("alpha", "Should not use alpha versions");
        version.Should().NotContain("-", "Should not use pre-release versions (indicated by hyphen)");

        // Verify version is 3.58.0 or later stable
        var versionMatch = Regex.Match(version, @"^(\d+)\.(\d+)\.(\d+)$");
        versionMatch.Success.Should().BeTrue("Version should be in format X.Y.Z");

        var major = int.Parse(versionMatch.Groups[1].Value);
        var minor = int.Parse(versionMatch.Groups[2].Value);

        major.Should().BeGreaterOrEqualTo(3, "Major version should be at least 3");
        if (major == 3)
        {
            minor.Should().BeGreaterOrEqualTo(58, "For version 3.x, minor should be >= 58");
        }
    }

    /// <summary>
    /// SECURITY (Issue #35): Verifies all .csproj files reference stable package versions.
    /// No project should have local pre-release Cosmos SDK overrides.
    /// </summary>
    [Fact]
    public void AllProjects_NoPreReleaseCosmosReferences()
    {
        var srcPath = Path.Combine(RepositoryRoot, "src");
        var csprojFiles = Directory.GetFiles(srcPath, "*.csproj", SearchOption.AllDirectories);

        csprojFiles.Should().NotBeEmpty("Should find .csproj files in src directory");

        foreach (var csprojPath in csprojFiles)
        {
            var content = File.ReadAllText(csprojPath);
            
            // Check for any Cosmos package references with explicit versions
            var doc = XDocument.Parse(content);
            var cosmosRefs = doc.Descendants("PackageReference")
                .Where(e => e.Attribute("Include")?.Value == "Microsoft.Azure.Cosmos");

            foreach (var cosmosRef in cosmosRefs)
            {
                var version = cosmosRef.Attribute("Version")?.Value;
                if (!string.IsNullOrEmpty(version))
                {
                    // If version is explicitly specified (not using central package management),
                    // verify it's not a pre-release
                    version.Should().NotContain("preview", 
                        $"Project {Path.GetFileName(csprojPath)} should not use preview Cosmos SDK");
                    version.Should().NotContain("-",
                        $"Project {Path.GetFileName(csprojPath)} should not use pre-release Cosmos SDK");
                }
            }
        }
    }

    /// <summary>
    /// SECURITY (Issue #35): Verifies Directory.Packages.props exists and enables central package management.
    /// This is part of the fix for Issue #35.
    /// </summary>
    [Fact]
    public void DirectoryPackages_Exists_AndEnablesCentralManagement()
    {
        var packagesPath = Path.Combine(RepositoryRoot, DirectoryPackagesPath);
        
        File.Exists(packagesPath).Should().BeTrue(
            "Directory.Packages.props should exist for centralized version management");

        var content = File.ReadAllText(packagesPath);
        var doc = XDocument.Parse(content);

        var manageCentrally = doc.Descendants("ManagePackageVersionsCentrally")
            .FirstOrDefault();

        manageCentrally.Should().NotBeNull(
            "ManagePackageVersionsCentrally property should be defined");
        manageCentrally!.Value.Should().Be("true",
            "Central package management should be enabled");
    }

    /// <summary>
    /// SECURITY (Issue #35): Regression test - verifies 3.59.0-preview.0 is NOT present anywhere.
    /// This was the vulnerable pre-release version that was removed.
    /// </summary>
    [Fact]
    public void NoProjectReferences_PreReleaseVersion3_59_0()
    {
        var srcPath = Path.Combine(RepositoryRoot, "src");
        var allFiles = Directory.GetFiles(srcPath, "*.*proj", SearchOption.AllDirectories)
            .Concat(new[] { Path.Combine(RepositoryRoot, DirectoryPackagesPath) })
            .Where(File.Exists);

        foreach (var filePath in allFiles)
        {
            var content = File.ReadAllText(filePath);
            
            content.Should().NotContain("3.59.0-preview",
                $"File {Path.GetFileName(filePath)} should not reference pre-release 3.59.0");
            content.Should().NotContain("3.59.0-preview.0",
                $"File {Path.GetFileName(filePath)} should not reference pre-release 3.59.0-preview.0");
        }
    }

    /// <summary>
    /// SECURITY (Issue #35): Verifies all .NET projects can resolve Cosmos SDK version.
    /// With central package management, projects should not specify versions locally.
    /// </summary>
    [Fact]
    public void AllProjects_UsesCentralPackageManagement()
    {
        var srcPath = Path.Combine(RepositoryRoot, "src");
        var csprojFiles = Directory.GetFiles(srcPath, "*.csproj", SearchOption.AllDirectories)
            .Where(f => !f.Contains(".Tests")); // Exclude test projects for this check

        foreach (var csprojPath in csprojFiles)
        {
            var content = File.ReadAllText(csprojPath);
            var doc = XDocument.Parse(content);

            // Check if project references Cosmos SDK
            var cosmosRefs = doc.Descendants("PackageReference")
                .Where(e => e.Attribute("Include")?.Value == "Microsoft.Azure.Cosmos");

            foreach (var cosmosRef in cosmosRefs)
            {
                var hasVersion = cosmosRef.Attribute("Version") != null;
                
                // With central package management, projects should NOT specify versions
                // (unless they need a specific override, which should be documented)
                if (hasVersion)
                {
                    var version = cosmosRef.Attribute("Version")!.Value;
                    // If version is specified, at minimum it should be stable
                    version.Should().NotContain("-",
                        $"Project {Path.GetFileName(csprojPath)} has explicit Cosmos version but it should be stable");
                }
            }
        }
    }
}
