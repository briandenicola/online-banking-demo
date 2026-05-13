namespace UserService;

/// <summary>
/// Centralised string literals used by user-service.
/// Prefer referencing these constants over hard-coded magic strings so that values
/// stay in sync across controllers, services, repositories, and tests.
/// </summary>
public static class Constants
{
    public const string ServiceName = "user-service";
    public const string DefaultStreamName = "banking-events";

    public static class Roles
    {
        public const string Admin = "admin";
        public const string User = "user";
    }

    public static class ClaimNames
    {
        public const string UserId = "userId";
    }

    public static class EventTypes
    {
        public const string UserRegistered = "UserRegistered";
    }

    public static class FailureReasons
    {
        public const string UserNotFound = "User not found";
        public const string AccountLocked = "Account locked";
        public const string InvalidPassword = "Invalid password";
    }

    public static class Browsers
    {
        public const string Chrome = "Chrome";
        public const string Firefox = "Firefox";
        public const string Safari = "Safari";
        public const string Edge = "Edge";
        public const string Other = "Other";
    }
}
