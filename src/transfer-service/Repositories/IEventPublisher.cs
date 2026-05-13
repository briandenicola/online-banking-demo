namespace TransferService.Repositories;

public interface IEventPublisher
{
    Task PublishAsync(string streamName, string payload);
}
