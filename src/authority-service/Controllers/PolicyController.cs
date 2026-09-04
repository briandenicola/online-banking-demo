using AuthorityService.Contracts;
using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace AuthorityService.Controllers;

[ApiController]
[Route("api/authority")]
[Authorize]
public class PolicyController : ControllerBase
{
    private readonly IPolicyProvider _policyProvider;
    private readonly IPolicyEvaluator _evaluator;
    private readonly ActorContextFactory _actors;

    public PolicyController(
        IPolicyProvider policyProvider,
        IPolicyEvaluator evaluator,
        ActorContextFactory actors)
    {
        _policyProvider = policyProvider;
        _evaluator = evaluator;
        _actors = actors;
    }

    /// <summary>
    /// The policy as RESOLVED — thresholds show their effective values and whether an env var
    /// overrode the file. A demo audience seeing "$500 (default)" vs "$500 (env)" is the whole
    /// point of making the override visible.
    /// </summary>
    [HttpGet("policy")]
    public IActionResult GetPolicy()
    {
        var policy = _policyProvider.Current;

        return Ok(new PolicySummaryResponse
        {
            PolicyId = policy.PolicyId,
            PolicyVersion = policy.PolicyVersion,
            ApiVersion = policy.Document.ApiVersion,
            LoadedAt = policy.LoadedAt,
            Thresholds = policy.Thresholds.Values
                .OrderBy(t => t.Name, StringComparer.Ordinal)
                .Select(t => new ThresholdView
                {
                    Name = t.Name,
                    Kind = t.Kind,
                    Env = t.Env,
                    Value = t.Value,
                    OverriddenByEnv = t.OverriddenByEnv,
                    Description = t.Description
                }).ToList(),
            Actions = policy.Document.ActionTypes
                .OrderBy(a => a.Key, StringComparer.Ordinal)
                .Select(a => new ActionView
                {
                    Id = a.Key,
                    DisplayName = a.Value.DisplayName,
                    BaseRung = a.Value.BaseRung,
                    AgentMayPropose = a.Value.AgentMayPropose,
                    RequiredEvidence = a.Value.RequiredEvidence
                }).ToList()
        });
    }

    /// <summary>
    /// Dry-run evaluation. Creates nothing — it exists so the agent can find out what a request
    /// would cost in human attention before asking for it.
    /// </summary>
    [HttpPost("evaluate")]
    public IActionResult Evaluate([FromBody] EvaluateRequest request)
    {
        var policy = _policyProvider.Current;
        var actor = _actors.Create(HttpContext.User);

        var decision = _evaluator.Evaluate(new EvaluationContext
        {
            ActionId = request.ActionId,
            Payload = request.Payload,
            Evidence = request.Evidence,
            Facts = request.Facts,
            Actor = actor
        }, policy);

        return Ok(new EvaluateResponse
        {
            ActionId = decision.ActionId,
            Outcome = decision.Outcome switch
            {
                DecisionOutcome.Admitted => "admitted",
                DecisionOutcome.UnderEvidenced => "under_evidenced",
                _ => "not_permitted"
            },
            BaseRung = RungOrder.ToWire(decision.BaseRung),
            RequiredRung = RungOrder.ToWire(decision.RequiredRung),
            RequiredSigners = decision.RequiredSigners,
            MinSeniority = decision.MinSeniority,
            TtlSeconds = decision.TtlSeconds,
            PolicyVersion = policy.PolicyVersion,
            FiredEscalators = decision.FiredEscalators.Select(FiredEscalatorView.From).ToList(),
            EvidenceGaps = decision.EvidenceGaps.ToList(),
            RejectionReason = decision.RejectionReason
        });
    }
}
