/**
 * Approval API — `authority-service`, via the existing axios client.
 *
 * Non-streaming calls go through `api/client.ts` so the bearer interceptor, the
 * 401 redirect, and error normalisation are all reused. That is the reason §4.1
 * chose SSE over a WebSocket in the first place: signing a $450k loan wants a
 * real HTTP status code, not a fire-and-forget socket frame.
 *
 * Endpoint paths come from `config/copilotConfig.ts`. Note that approvals live
 * under `/api/authority/`, NOT `/api/copilot/` — one prefix per service, so the
 * enforcement boundary is legible in the URL and cannot be re-routed to the
 * harness by nginx location ordering.
 */

import apiClient from './client';
import { authorityUrl, getCopilotConfig } from '../config/copilotConfig';
import { Approval } from '../components/copilot/types';
import { toApproval, WireApproval, WireApprovalList } from './authorityWire';

/**
 * `mine` — approvals this actor requested.
 * `awaiting-me` — the co-sign queue. The server EXCLUDES the caller's own
 * requests from it, so a supervisor never sees a request they could not sign.
 * The queue keys on required seniority, never on a named person.
 */
export type ApprovalScope = 'mine' | 'awaiting-me' | 'session' | 'all';

export interface ListApprovalsParams {
  scope?: ApprovalScope;
  status?: string;
  sessionId?: string;
  actionId?: string;
  limit?: number;
}

function approvalsPath(suffix = ''): string {
  const { endpoints } = getCopilotConfig();
  return authorityUrl(`${endpoints.approvals}${suffix}`);
}

export async function listApprovals(params: ListApprovalsParams = {}): Promise<Approval[]> {
  const response = await apiClient.get<WireApprovalList>(approvalsPath(), { params });
  const items = response.data && Array.isArray(response.data.items) ? response.data.items : [];
  return items.map(toApproval);
}

export async function getApproval(id: string): Promise<Approval> {
  const response = await apiClient.get<WireApproval>(approvalsPath(`/${encodeURIComponent(id)}`));
  return toApproval(response.data);
}

export interface SignArgs {
  comment?: string;
  /**
   * The hash the card actually displayed.
   *
   * Optional on the wire, always sent from here. It is the client half of the
   * TOCTOU defence: if the payload changed between render and click, the server
   * rejects rather than applying a signature to something the human never saw.
   * Omitting it would make the hash on the card decorative.
   */
  expectedPayloadHash: string;
}

export async function signApproval(id: string, args: SignArgs): Promise<Approval> {
  const response = await apiClient.post<WireApproval>(
    approvalsPath(`/${encodeURIComponent(id)}/sign`),
    { comment: args.comment, expectedPayloadHash: args.expectedPayloadHash }
  );
  return toApproval(response.data);
}

export async function denyApproval(id: string, reason: string): Promise<Approval> {
  const response = await apiClient.post<WireApproval>(
    approvalsPath(`/${encodeURIComponent(id)}/deny`),
    { reason }
  );
  return toApproval(response.data);
}

/**
 * Executes a signed approval.
 *
 * A 409 here is NOT a generic failure: it means the policy re-evaluated to a
 * higher rung between signature and execution, the signature is void, and a
 * replacement approval may be offered. The caller must render that specifically
 * (POLICY_RUNG_ESCALATED) — a banker who signed in good faith and finds it
 * un-signed deserves the reason, and generic errors here train people to
 * distrust the approval card this whole epic rests on.
 */
export interface ExecuteResult {
  approval: Approval;
  escalated: boolean;
  replacement?: Approval;
  message?: string;
}

export async function executeApproval(id: string): Promise<ExecuteResult> {
  try {
    const response = await apiClient.post<WireApproval>(
      approvalsPath(`/${encodeURIComponent(id)}/execute`)
    );
    return { approval: toApproval(response.data), escalated: false };
  } catch (error) {
    const err = error as {
      response?: {
        status?: number;
        data?: { error?: string; message?: string; approval?: WireApproval; replacement?: WireApproval | null };
      };
    };
    const data = err.response?.data;
    if (err.response?.status === 409 && data?.approval) {
      return {
        approval: toApproval(data.approval),
        escalated: true,
        replacement: data.replacement ? toApproval(data.replacement) : undefined,
        message: data.message,
      };
    }
    throw error;
  }
}
