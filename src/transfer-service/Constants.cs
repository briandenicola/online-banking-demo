namespace TransferService;

/// <summary>
/// Centralised string literals used by transfer-service.
/// </summary>
public static class Constants
{
    public const string ServiceName = "transfer-service";
    public const string DefaultStreamName = "banking-events";

    public static class TransferStatuses
    {
        public const string Pending = "Pending";
        public const string Processing = "Processing";
        public const string Completed = "Completed";
        public const string Failed = "Failed";
    }

    public static class TransactionTypes
    {
        public const string Transfer = "Transfer";
    }

    public static class Categories
    {
        public const string Transfer = "Transfer";
    }

    public static class ClaimNames
    {
        public const string UserId = "userId";
    }

    public static class EventTypes
    {
        public const string TransferInitiated = "TransferInitiated";
    }

    public static class FailureReasons
    {
        public const string ServiceCommunication = "Transfer could not be completed due to a service communication error";
        public const string Generic = "Transfer could not be completed";
        public const string Storage = "Transfer could not be completed due to a storage error";
    }
}
