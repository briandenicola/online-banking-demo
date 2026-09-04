using System.Text.RegularExpressions;
using AuthorityService.Contracts;
using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Services;

/// <summary>
/// The whole approval lifecycle, in one place. Every state change in this service passes
/// through this type and then through the single-writer repository.
/// </summary>
public class ApprovalService
{
    private static readonly Regex PathPlaceholder = new(@"\{([a-zA-Z0-9_.]+)\}", RegexOptions.Compiled);

    private readonly IApprovalRepository _repository;
    private readonly IPolicyProvider _policyProvider;
    private readonly IPolicyEvaluator _evaluator;
    private readonly ISignatureService _signatures;
    private readonly IDenialReasonValidator _denialReasons;
    private readonly IAuditPublisher _audit;
    private readonly IActionBroker _broker;
    private readonly ILogger<ApprovalService> _logger;

    public ApprovalService(
        IApprovalRepository repository,
        IPolicyProvider policyProvider,
        IPolicyEvaluator evaluator,
        ISignatureService signatures,
        IDenialReasonValidator denialReasons,
        IAuditPublisher audit,
        IActionBroker broker,
        ILogger<ApprovalService> logger)
    {
        _repository = repository;
        _policyProvider = policyProvider;
        _evaluator = evaluator;
        _signatures = signatures;
        _denialReasons = denialReasons;
        _audit = audit;
        _broker = broker;
        _logger = logger;
    }

    // =====================================================================================
    // PROPOSE
    // =====================================================================================

    public async Task<Approval> ProposeAsync(
        ProposeRequest request,
        ActorContext actor,
        string? correlationId,
        CancellationToken ct = default)
    {
        var policy = _policyProvider.Current;

        var context = new EvaluationContext
        {
            ActionId = request.ActionId,
            Payload = request.Payload,
            Evidence = request.Evidence,
            Facts = request.Facts,
            Actor = actor
        };

        var decision = _evaluator.Evaluate(context, policy);

        // The requester must hold standing in the banking ladder. Proposing is not signing, but
        // an approval proposed by a principal with no standing is a queue entry a supervisor may
        // act on believing a banker raised it — and, before the role model was made single-source,
        // a customer's token was one such principal. Set membership, not a count: the actor must
        // clear the bar of the FIRST slot, which is derived from the roles that may sign at all.
        if (decision.Admissible && actor.Seniority < decision.SignerSlots.Min(slot => slot.MinSeniority))
        {
            throw new AuthorityException("not_permitted",
                "Only a principal with banking seniority may raise an approval for this action.", 403);
        }

        if (!decision.Admissible)
        {
            await _audit.PublishAsync(
                SharedIdentifiers.Events.ActionProposalRejected,
                AuditEvents.ActionProposalRejected(
                    request.ActionId, actor.UserId, request.SessionId,
                    decision.RejectionReason ?? "Refused by policy.", correlationId),
                ct);

            var status = decision.Outcome == DecisionOutcome.UnderEvidenced ? 422 : 403;

            throw new AuthorityException(
                decision.Outcome == DecisionOutcome.UnderEvidenced ? "evidence_incomplete" : "not_permitted",
                decision.RejectionReason ?? "Refused by policy.",
                status,
                new { evidenceGaps = decision.EvidenceGaps, requiredRung = RungOrder.ToWire(decision.RequiredRung) });
        }

        var approval = BuildApproval(request, actor, decision, policy, correlationId);

        // A supersede must not leave two live approvals for the same intent. The new one is
        // written first so the old one's supersededByApprovalId can never dangle.
        Approval? superseded = null;

        if (!string.IsNullOrWhiteSpace(request.SupersedesApprovalId))
        {
            superseded = await _repository.FindAsync(request.SupersedesApprovalId, ct)
                         ?? throw new AuthorityException("not_found",
                             $"Approval {request.SupersedesApprovalId} does not exist.", 404);

            if (!string.Equals(superseded.RequesterId, actor.UserId, StringComparison.Ordinal))
            {
                throw new AuthorityException("forbidden",
                    "Only the original requester may supersede an approval.", 403);
            }

            if (superseded.IsTerminal)
            {
                throw new AuthorityException("conflict",
                    $"Approval {superseded.Id} is already terminal " +
                    $"({EnumWire.ToWire(superseded.Status)}) and cannot be superseded.", 409);
            }

            approval.SupersedesApprovalId = superseded.Id;
        }

        await _repository.CreateAsync(approval, ct);
        approval = await _repository.MarkPendingAsync(approval, ct);

        if (superseded is not null)
        {
            // The agent re-planned. The old approval dies with PAYLOAD_SUPERSEDED — never
            // SUPERSEDED_BY_REPLAN, and never a silent mutation of the original payload.
            superseded = await _repository.TransitionTerminalAsync(
                superseded,
                TerminalReason.PayloadSuperseded,
                $"Replaced by {approval.Id} after the agent revised the plan.",
                approval.Id,
                ct);

            await _audit.PublishAsync(
                SharedIdentifiers.Events.ApprovalDenied, AuditEvents.ApprovalDenied(superseded), ct);
        }

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalProposed, AuditEvents.ApprovalProposed(approval), ct);

        if (approval.FiredEscalators.Count > 0)
        {
            await _audit.PublishAsync(
                SharedIdentifiers.Events.PolicyEscalated, AuditEvents.PolicyEscalated(approval), ct);
        }

        return approval;
    }

    private Approval BuildApproval(
        ProposeRequest request,
        ActorContext actor,
        PolicyDecision decision,
        ResolvedPolicy policy,
        string? correlationId,
        string? forcedId = null)
    {
        var action = policy.Action(request.ActionId)!;
        var scale = policy.Document.Defaults.CurrencyScale;
        var id = forcedId ?? SharedIdentifiers.ApprovalIdPrefix + Guid.NewGuid().ToString("N")[..24];
        var now = DateTime.UtcNow;
        var expires = now.AddSeconds(decision.TtlSeconds);

        var approval = new Approval
        {
            Id = id,
            RequesterId = actor.UserId,
            RequesterUsername = actor.Username,
            RequesterRoles = actor.EffectiveRoles.ToList(),
            RequesterSeniority = actor.Seniority,
            RequesterSelfDealing = actor.SelfDealing,
            Status = ApprovalStatus.Proposed,
            ActionId = request.ActionId,
            ActionLabel = action.DisplayName,
            SessionId = request.SessionId,
            AgentId = request.AgentId,
            CorrelationId = correlationId,
            Payload = request.Payload,
            Evidence = request.Evidence,
            Facts = request.Facts,
            AgentAssessment = request.AgentAssessment,
            HashFields = action.HashFields.ToList(),
            MoneyFields = action.MoneyFields.ToList(),
            CurrencyScale = scale,
            PolicyVersion = policy.PolicyVersion,
            PolicyId = policy.PolicyId,
            BaseRung = decision.BaseRung,
            RequiredRung = decision.RequiredRung,
            RequiredSigners = decision.RequiredSigners,
            MinSeniority = decision.MinSeniority,
            FiredEscalators = decision.FiredEscalators.ToList(),
            ResolvedThresholdSnapshot = decision.ResolvedThresholdSnapshot.ToDictionary(
                kv => kv.Key, kv => kv.Value, StringComparer.Ordinal),
            SignatureSlots = decision.SignerSlots.ToList(),
            CreatedAt = now,
            ExpiresAt = expires,
            ExpiresAtEpoch = new DateTimeOffset(expires, TimeSpan.Zero).ToUnixTimeSeconds(),
            Target = ResolveTarget(action, request.Payload)
        };

        // policyVersion is bound into the hash, so a signature can never be presented as
        // though it had been produced under a different ruleset (design §6.2.1).
        approval.PayloadHash = PayloadHasher.Compute(
            request.Payload, action, request.ActionId, policy.PolicyVersion, scale);

        approval.PendingSlotOrdinal = approval.SignatureSlots.Min(s => s.Ordinal);
        approval.AwaitingSeniority = approval.SignatureSlots
            .OrderBy(s => s.Ordinal).First().MinSeniority;

        return approval;
    }

    private static ApprovalTarget ResolveTarget(ActionDefinition action, JObject payload)
    {
        if (action.Target is null) return new ApprovalTarget();

        var resolved = PathPlaceholder.Replace(action.Target.Path, match =>
        {
            var token = payload.SelectToken(match.Groups[1].Value);

            if (token is null || token.Type == JTokenType.Null)
            {
                throw new AuthorityException("invalid_payload",
                    $"The action target path requires '{match.Groups[1].Value}' but the payload " +
                    "does not supply it.", 400);
            }

            return Uri.EscapeDataString(token.ToString());
        });

        return new ApprovalTarget
        {
            Service = action.Target.Service,
            Method = action.Target.Method,
            PathTemplate = action.Target.Path,
            ResolvedPath = resolved
        };
    }

    // =====================================================================================
    // READ
    // =====================================================================================

    public async Task<Approval> GetAsync(string id, ActorContext actor, CancellationToken ct = default)
    {
        var approval = await _repository.FindAsync(id, ct)
                       ?? throw new AuthorityException("not_found", $"Approval {id} does not exist.", 404);

        return await ApplyLazyExpiryAsync(approval, ct);
    }

    public async Task<IReadOnlyList<Approval>> ListAsync(ApprovalQuery query, CancellationToken ct = default)
    {
        var results = await _repository.QueryAsync(query, ct);
        var projected = new List<Approval>(results.Count);

        foreach (var approval in results)
        {
            // Read-side expiry: an approval that is past its TTL must never be presented as
            // actionable just because the sweeper has not reached it yet (design §5.4).
            projected.Add(await ApplyLazyExpiryAsync(approval, ct));
        }

        return projected;
    }

    /// <summary>
    /// Whether the CALLER may sign this approval right now, and if not, why. Computed on the
    /// server so the UI never has to derive an authorization answer.
    /// </summary>
    public (bool CanSign, string? Reason) EvaluateSignEligibility(Approval approval, ActorContext actor)
    {
        if (approval.Status != ApprovalStatus.Pending)
        {
            return (false, $"This approval is {EnumWire.ToWire(approval.Status)} and is not awaiting a signature.");
        }

        var slot = NextSlot(approval);

        if (slot is null) return (false, "Every signature slot is already filled.");

        if (slot.MustDifferFrom.Contains(actor.UserId, StringComparer.Ordinal))
        {
            return (false,
                "You requested this action, so you cannot also approve it. Dual control means " +
                "two people, not two clicks.");
        }

        if (approval.SignerIds.Contains(actor.UserId, StringComparer.Ordinal))
        {
            return (false, "You have already signed this approval. A second signature must come from someone else.");
        }

        if (actor.Seniority < slot.MinSeniority)
        {
            return (false,
                $"This approval requires a signer at seniority {slot.MinSeniority} or above; " +
                $"your role carries seniority {actor.Seniority}.");
        }

        return (true, null);
    }

    // =====================================================================================
    // SIGN
    // =====================================================================================

    public async Task<Approval> SignAsync(
        string id, ActorContext actor, SignRequest request, string tokenJti, CancellationToken ct = default)
    {
        var approval = await _repository.FindAsync(id, ct)
                       ?? throw new AuthorityException("not_found", $"Approval {id} does not exist.", 404);

        approval = await ApplyLazyExpiryAsync(approval, ct);

        var (canSign, reason) = EvaluateSignEligibility(approval, actor);

        if (!canSign)
        {
            var status = approval.IsTerminal || approval.Status != ApprovalStatus.Pending ? 409 : 403;
            throw new AuthorityException("cannot_sign", reason!, status);
        }

        if (!string.IsNullOrWhiteSpace(request.ExpectedPayloadHash) &&
            !string.Equals(request.ExpectedPayloadHash, approval.PayloadHash, StringComparison.Ordinal))
        {
            throw new AuthorityException("payload_hash_mismatch",
                "The payload changed since it was shown to you. Re-read the request before signing.",
                409);
        }

        VerifyStoredHash(approval);

        var slot = NextSlot(approval)!;
        var signedAt = DateTime.UtcNow;
        var nonce = Guid.NewGuid().ToString("N");

        var signature = _signatures.Sign(new SigningInput(
            approval.Id, approval.ActionId, approval.PolicyVersion, approval.PayloadHash,
            actor.UserId, tokenJti, slot.Ordinal, signedAt, nonce));

        // Quorum is a count of FILLED SLOTS, not a tally of distinct identities. Separation of
        // duties is already enforced per slot by `mustDifferFrom` — a set-membership test against
        // a named subject, which fails loudly, where a distinct-identity tally is satisfied by
        // arithmetic and a miscount passes silently (Danny, 2026-09-04).
        var quorum = approval.SignaturesCollected + 1 >= approval.RequiredSigners;

        approval = await _repository.RecordSignatureAsync(approval, slot.Ordinal, new SignatureSlot
        {
            Ordinal = slot.Ordinal,
            SignedBy = actor.UserId,
            SignedByUsername = actor.Username,
            SignedAt = signedAt,
            Signature = signature,
            SignerTokenJti = tokenJti,
            Nonce = nonce,
            Comment = request.Comment
        }, quorum, ct);

        var filled = approval.SignatureSlots.Single(s => s.Ordinal == slot.Ordinal);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalSigned, AuditEvents.ApprovalSigned(approval, filled), ct);

        return approval;
    }

    // =====================================================================================
    // DENY
    // =====================================================================================

    public async Task<Approval> DenyAsync(
        string id, ActorContext actor, DenyRequest request, CancellationToken ct = default)
    {
        var approval = await _repository.FindAsync(id, ct)
                       ?? throw new AuthorityException("not_found", $"Approval {id} does not exist.", 404);

        approval = await ApplyLazyExpiryAsync(approval, ct);

        if (approval.IsTerminal)
        {
            throw new AuthorityException("conflict",
                $"Approval {id} is already terminal ({EnumWire.ToWire(approval.Status)}).", 409);
        }

        if (approval.Status == ApprovalStatus.Signed)
        {
            throw new AuthorityException("conflict",
                "This approval is fully signed and awaiting execution; it can no longer be denied.", 409);
        }

        var isRequester = string.Equals(approval.RequesterId, actor.UserId, StringComparison.Ordinal);
        var slot = NextSlot(approval);

        if (!isRequester && (slot is null || actor.Seniority < slot.MinSeniority))
        {
            throw new AuthorityException("forbidden",
                "You are neither the requester nor an eligible approver for this action.", 403);
        }

        // A denial reason is mandatory and validated. "no" is not a reason — the person who
        // reads this in six months is the point (epic §5.4.2).
        var validation = _denialReasons.Validate(request.Reason);

        if (!validation.IsValid)
        {
            throw new AuthorityException("invalid_denial_reason", validation.Message!, 400,
                new { rule = validation.FailedRule });
        }

        approval = await _repository.TransitionTerminalAsync(
            approval, TerminalReason.HumanDenied, request.Reason.Trim(), null, ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalDenied, AuditEvents.ApprovalDenied(approval), ct);

        return approval;
    }

    // =====================================================================================
    // EXECUTE — the §5.3.2 gate
    // =====================================================================================

    public record ExecuteResult(Approval Approval, Approval? Replacement, bool Voided);

    /// <summary>
    /// The ONLY path from <c>signed</c> to <c>executed</c>. The checks below run in this exact
    /// order (design §8.8); re-evaluation happens BEFORE any downstream call, because a gate
    /// that runs after the money moves is not a gate.
    /// </summary>
    public async Task<ExecuteResult> ExecuteAsync(
        string id, ActorContext actor, string? bearerToken, CancellationToken ct = default)
    {
        // 1. Exists.
        var approval = await _repository.FindAsync(id, ct)
                       ?? throw new AuthorityException("not_found", $"Approval {id} does not exist.", 404);

        // 2. Not expired (read-side, before anything else can act on it).
        approval = await ApplyLazyExpiryAsync(approval, ct);

        // 3. Status is exactly `signed`.
        if (approval.Status != ApprovalStatus.Signed)
        {
            throw new AuthorityException("conflict",
                $"Only a fully signed approval may be executed; this one is " +
                $"'{EnumWire.ToWire(approval.Status)}'.", 409);
        }

        // 4. Not already executed or in flight.
        if (approval.Execution.State == ExecutionState.InFlight)
        {
            throw new AuthorityException("conflict",
                "This approval is already being executed.", 409);
        }

        // 5. Quorum and separation of duties, re-verified server-side rather than trusted.
        if (approval.SignaturesCollected < approval.RequiredSigners)
        {
            throw new AuthorityException("insufficient_signatures",
                $"This approval requires {approval.RequiredSigners} signature(s); it carries " +
                $"{approval.SignaturesCollected}.", 409);
        }

        // Separation of duties, re-verified from the slots rather than assumed. At L1 the
        // requester IS the approver — the agent proposed, the banker signs. At L2 the second
        // slot carries mustDifferFrom, and that is what must hold.
        foreach (var slot in approval.SignatureSlots.Where(s => s.SignedBy is not null))
        {
            if (slot.MustDifferFrom.Contains(slot.SignedBy!, StringComparer.Ordinal))
            {
                throw new AuthorityException("separation_of_duties",
                    $"Slot {slot.Ordinal} was signed by an identity it was required to differ " +
                    "from. Refusing to execute.", 409);
            }
        }

        // 6. The payload still hashes to what was signed.
        VerifyStoredHash(approval);

        // 7. Every signature verifies against the stored payload hash.
        VerifySignatures(approval);

        // 8. Re-evaluate under the CURRENT policy (epic §5.3.2).
        //
        //    The split that matters: the HASH is recomputed under the policyVersion stored on
        //    the approval (it is part of the signed preimage and must not move), while the RUNG
        //    is re-derived under the LIVE policy. Getting these backwards turns this ruling into
        //    "any policy edit invalidates every outstanding approval".
        var currentPolicy = _policyProvider.Current;
        var reEvaluation = ReEvaluate(approval, currentPolicy);

        if (reEvaluation.Outcome != DecisionOutcome.Admitted ||
            reEvaluation.RequiredRung > approval.RequiredRung)
        {
            return await VoidForPolicyEscalationAsync(approval, currentPolicy, reEvaluation, ct);
        }

        // Unchanged or LOWER: honor the existing approval. The rung is never rewritten
        // downward — a signature already collected is not retroactively made unnecessary, and
        // "the rules relaxed while you waited" must never mean "your approval was silently
        // downgraded".

        // 9. Claim execution with an etag-guarded write. Two concurrent executes: one wins.
        try
        {
            approval = await _repository.BeginExecutionAsync(approval, ct);
        }
        catch (ApprovalConcurrencyException)
        {
            throw new AuthorityException("conflict",
                "This approval is already being executed by another request.", 409);
        }

        var result = await _broker.ExecuteAsync(approval, bearerToken, ct);

        if (!result.Succeeded)
        {
            // Status stays `signed`. A downstream failure does not invalidate the human
            // decision, so a retry needs no new signature — and the retry re-enters this gate.
            approval = await _repository.FailExecutionAsync(
                approval, result.Error ?? "Downstream call failed.", result.StatusCode, ct);

            await _audit.PublishAsync(
                SharedIdentifiers.Events.ApprovalExecutionFailed,
                AuditEvents.ApprovalExecutionFailed(approval, result.Error ?? "Downstream call failed."), ct);

            throw new AuthorityException("execution_failed", result.Error ?? "Downstream call failed.", 502,
                new { approvalId = approval.Id, status = EnumWire.ToWire(approval.Status) });
        }

        approval = await _repository.CompleteExecutionAsync(
            approval, result.StatusCode ?? 200, result.DownstreamRef, currentPolicy.PolicyVersion, ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalExecuted, AuditEvents.ApprovalExecuted(approval), ct);

        return new ExecuteResult(approval, null, false);
    }

    private async Task<ExecuteResult> VoidForPolicyEscalationAsync(
        Approval approval, ResolvedPolicy currentPolicy, PolicyDecision reEvaluation, CancellationToken ct)
    {
        var signedRung = approval.RequiredRung;
        var signedPolicyVersion = approval.PolicyVersion;

        Approval? replacement = null;

        if (reEvaluation.Admissible)
        {
            // A replacement is created at the NEW, higher rung. The signatures do not carry
            // over: they were given under a ruleset that has since been judged insufficient.
            var request = new ProposeRequest
            {
                ActionId = approval.ActionId,
                Payload = approval.Payload,
                Evidence = approval.Evidence,
                Facts = approval.Facts,
                AgentAssessment = approval.AgentAssessment,
                SessionId = approval.SessionId,
                AgentId = approval.AgentId
            };

            var requesterContext = RequesterContext(approval, currentPolicy);

            replacement = BuildApproval(
                request, requesterContext, reEvaluation, currentPolicy, approval.CorrelationId);

            replacement.SupersedesApprovalId = approval.Id;

            await _repository.CreateAsync(replacement, ct);
            replacement = await _repository.MarkPendingAsync(replacement, ct);
        }

        var detail = reEvaluation.Admissible
            ? $"Policy changed between signing and execution: this action now requires " +
              $"{RungOrder.ToWire(reEvaluation.RequiredRung)} (it was signed at " +
              $"{RungOrder.ToWire(signedRung)}). A replacement approval was raised at the new rung."
            : $"Policy changed between signing and execution: this action is no longer permitted. " +
              (reEvaluation.RejectionReason ?? string.Empty);

        approval = await _repository.TransitionTerminalAsync(
            approval, TerminalReason.PolicyRungEscalated, detail, replacement?.Id, ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalVoidedByPolicyChange,
            AuditEvents.ApprovalVoidedByPolicyChange(
                approval, signedPolicyVersion, currentPolicy.PolicyVersion,
                signedRung, reEvaluation.RequiredRung, reEvaluation.FiredEscalators), ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalDenied, AuditEvents.ApprovalDenied(approval), ct);

        if (replacement is not null)
        {
            await _audit.PublishAsync(
                SharedIdentifiers.Events.ApprovalProposed, AuditEvents.ApprovalProposed(replacement), ct);
        }

        return new ExecuteResult(approval, replacement, true);
    }

    /// <summary>
    /// Re-runs the evaluator over the FROZEN inputs under the given policy. Public so tests can
    /// drive both directions of §5.3.2 without going through HTTP.
    /// </summary>
    public PolicyDecision ReEvaluate(Approval approval, ResolvedPolicy policy)
    {
        var context = new EvaluationContext
        {
            ActionId = approval.ActionId,
            Payload = approval.Payload,
            Evidence = approval.Evidence,
            Facts = approval.Facts,
            Actor = RequesterContext(approval, policy)
        };

        return _evaluator.Evaluate(context, policy);
    }

    private static ActorContext RequesterContext(Approval approval, ResolvedPolicy policy) => new()
    {
        UserId = approval.RequesterId,
        Username = approval.RequesterUsername,
        Role = approval.RequesterRoles.FirstOrDefault(),
        EffectiveRoles = approval.RequesterRoles,
        Seniority = approval.RequesterSeniority,
        SessionId = approval.SessionId,
        SelfDealing = approval.RequesterSelfDealing
    };

    // =====================================================================================
    // EXPIRY
    // =====================================================================================

    /// <summary>
    /// Expiry is a DENIAL, never an approval. Called by the sweeper and by every read path,
    /// because a pending approval past its TTL must not be presented as actionable just because
    /// the sweeper has not reached it yet.
    /// </summary>
    public async Task<Approval> ExpireAsync(Approval approval, CancellationToken ct = default)
    {
        var age = (int)Math.Max(0, (DateTime.UtcNow - approval.CreatedAt).TotalSeconds);

        approval = await _repository.TransitionTerminalAsync(
            approval,
            TerminalReason.TtlExpired,
            $"No decision was recorded before {approval.ExpiresAt:O}. An unanswered request is a " +
            "refused request.",
            null,
            ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalExpired, AuditEvents.ApprovalExpired(approval, age), ct);

        await _audit.PublishAsync(
            SharedIdentifiers.Events.ApprovalDenied, AuditEvents.ApprovalDenied(approval), ct);

        return approval;
    }

    private async Task<Approval> ApplyLazyExpiryAsync(Approval approval, CancellationToken ct)
    {
        if (approval.Status != ApprovalStatus.Pending) return approval;

        if (approval.ExpiresAtEpoch > DateTimeOffset.UtcNow.ToUnixTimeSeconds()) return approval;

        _logger.LogInformation(
            "Approval {ApprovalId} passed its TTL and is being denied on read", approval.Id);

        return await ExpireAsync(approval, ct);
    }

    // =====================================================================================
    // Integrity helpers
    // =====================================================================================

    /// <summary>
    /// Recomputes the payload hash from the STORED payload and compares it with the STORED hash.
    ///
    /// <para>
    /// Read honestly, this is a self-consistency check, not a tamper check: an attacker who can
    /// rewrite the stored payload can rewrite the stored hash beside it (Livingston, F-2). What
    /// actually stops a payload being swapped between signature and execution is structural —
    /// <c>ExecuteAsync</c> takes NO payload parameter, so there is no caller-supplied payload for
    /// it to prefer, and the signatures verify against this same frozen preimage. This check earns
    /// its place by catching serializer drift and partial writes, and it is worth keeping for
    /// that; it is not the control that makes execution safe.
    /// </para>
    /// </summary>
    private static void VerifyStoredHash(Approval approval)
    {
        // Recomputed from the fields FROZEN ON THE DOCUMENT — including its own policyVersion.
        // Deliberately not from the live policy: the hash is part of a signed preimage and must
        // stay stable across policy edits (design §6.4).
        var action = new ActionDefinition
        {
            HashFields = approval.HashFields,
            MoneyFields = approval.MoneyFields
        };

        string recomputed;

        try
        {
            recomputed = PayloadHasher.Compute(
                approval.Payload, action, approval.ActionId, approval.PolicyVersion, approval.CurrencyScale);
        }
        catch (CanonicalizationException ex)
        {
            throw new AuthorityException("payload_not_canonicalizable", ex.Message, 409);
        }

        if (!string.Equals(recomputed, approval.PayloadHash, StringComparison.Ordinal))
        {
            throw new AuthorityException("payload_hash_mismatch",
                "The stored payload no longer hashes to the value that was signed. Refusing to act.",
                409);
        }
    }

    private void VerifySignatures(Approval approval)
    {
        foreach (var slot in approval.SignatureSlots.Where(s => s.SignedBy is not null))
        {
            var valid = _signatures.Verify(new SigningInput(
                approval.Id, approval.ActionId, approval.PolicyVersion,
                approval.PayloadHash, slot.SignedBy!, slot.SignerTokenJti ?? string.Empty,
                slot.Ordinal, slot.SignedAt!.Value, slot.Nonce ?? string.Empty), slot.Signature ?? string.Empty);

            if (!valid)
            {
                throw new AuthorityException("signature_invalid",
                    $"The signature in slot {slot.Ordinal} does not verify. Refusing to execute.", 409);
            }
        }
    }

    private static SignatureSlot? NextSlot(Approval approval) =>
        approval.SignatureSlots
            .Where(s => s.SignedBy is null)
            .OrderBy(s => s.Ordinal)
            .FirstOrDefault();
}
