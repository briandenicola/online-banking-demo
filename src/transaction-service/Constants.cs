namespace TransactionService;

/// <summary>
/// Centralised string literals used by transaction-service.
/// </summary>
public static class Constants
{
    public const string ServiceName = "transaction-service";
    public const string DefaultStreamName = "banking-events";

    public static class Currencies
    {
        public const string USD = "USD";
    }

    public static class TransactionTypes
    {
        public const string Debit = "Debit";
        public const string Credit = "Credit";
        public const string Transfer = "Transfer";
    }

    public static class TransactionStatuses
    {
        public const string Pending = "Pending";
        public const string Completed = "Completed";
        public const string Failed = "Failed";
    }

    public static class Categories
    {
        public const string Uncategorized = "Uncategorized";
        public const string Transfer = "Transfer";
    }

    public static class ClaimNames
    {
        public const string UserId = "userId";
    }

    public static class EventTypes
    {
        public const string TransactionCreated = "TransactionCreated";
        public const string InsufficientFundsAttempt = "InsufficientFundsAttempt";
    }
}
