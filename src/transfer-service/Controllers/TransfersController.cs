using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;
using TransferService.Services;

namespace TransferService.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class TransfersController : ControllerBase
{
    private readonly ITransferService _transferService;
    private readonly ILogger<TransfersController> _logger;

    public TransfersController(ITransferService transferService, ILogger<TransfersController> logger)
    {
        _transferService = transferService;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> InitiateTransfer([FromBody] CreateTransferRequest request)
    {
        var userId = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userId))
        {
            return Unauthorized();
        }

        var transfer = await _transferService.InitiateTransferAsync(userId, request);

        if (transfer.Status == "Failed")
        {
            return BadRequest(new { error = transfer.FailureReason, transfer });
        }

        return CreatedAtAction(nameof(GetTransfer), new { id = transfer.Id }, transfer);
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetTransfer(string id)
    {
        var transfer = await _transferService.GetTransferByIdAsync(id);
        if (transfer == null)
        {
            return NotFound();
        }
        return Ok(transfer);
    }
}