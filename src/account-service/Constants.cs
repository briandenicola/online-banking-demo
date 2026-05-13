namespace AccountService;

/// <summary>
/// Centralised string literals used by account-service.
/// </summary>
public static class Constants
{
    public const string ServiceName = "account-service";
    public const string AccountNumberPrefix = "ACC";

    public static class Currencies
    {
        public const string USD = "USD";
    }

    public static class AccountTypes
    {
        public const string Checking = "Checking";
        public const string Savings = "Savings";
    }

    public static class ClaimNames
    {
        public const string UserId = "userId";
    }
}
