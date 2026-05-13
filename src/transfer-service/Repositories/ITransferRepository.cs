using TransferService.Models;

namespace TransferService.Repositories;

public interface ITransferRepository
{
    Task<Transfer?> GetByIdAsync(string id);
    Task<Transfer> CreateAsync(Transfer transfer);
}
