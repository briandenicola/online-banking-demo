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

        // Banking authority ladder (epic #332 §5.8.2, RATIFIED).
        // supervisor implies banker. admin implies NEITHER — platform authority
        // and banking authority are different axes, and collapsing them would
        // let one identity satisfy both signatures on an L2 approval.
        // Expansion rules live in config/role-hierarchy.yaml, not here.
        public const string Banker = "banker";
        public const string Supervisor = "supervisor";
    }

    public static class ClaimNames
    {
        public const string UserId = "userId";

        /// <summary>
        /// Array claim holding the role plus everything it implies, expanded
        /// once at token issuance. Consumers check this, never the flat
        /// <c>role</c> claim, and never re-implement the expansion.
        /// A token issued before this change carries no such claim; readers must
        /// treat its absence as <c>[role]</c> so old tokens degrade gracefully
        /// instead of 401-ing.
        /// </summary>
        public const string EffectiveRoles = "effectiveRoles";

        /// <summary>
        /// Banking seniority of the signer, used by approval signature slots
        /// (<c>minSeniority</c>). Derived from the role hierarchy.
        /// </summary>
        public const string Seniority = "seniority";
    }

    public static class EventTypes
    {
        public const string UserRegistered = "UserRegistered";

        /// <summary>
        /// A role was granted to an identity. Emitted on every promotion,
        /// including the out-of-band bootstrap seed, because role promotion is
        /// itself an L3 action and must never happen without an audit record.
        /// </summary>
        /// <remarks>
        /// Epic §5.8.3 writes this as <c>authority.role.granted</c>. Every event
        /// already on the <c>banking-events</c> stream is PascalCase and the Go
        /// consumer switches on PascalCase names, so the dotted form would have
        /// been silently unauditable. Raised in
        /// .squad/decisions/inbox/rusty-role-granted-event-naming.md.
        /// </remarks>
        public const string RoleGranted = "RoleGranted";
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
