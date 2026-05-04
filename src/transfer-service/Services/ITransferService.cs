using System.Threading.Tasks;
using TransferService.Models;
using OnlineBankingDemo.Contracts.Dtos;

namespace TransferService.Services;

public interface ITransferService
{
    Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request);
    Task<Transfer?> GetTransferByIdAsync(string id);
}