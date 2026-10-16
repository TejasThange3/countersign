/**
 * Client for the Countersign voice agent's text-mode API (apps/agent/src/countersign_agent/app.py).
 * The browser talks to the agent directly; the agent only accepts this site's origin (CORS_ORIGINS).
 */

export const AGENT_URL = (process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:7860").replace(/\/$/, "");

export type Decision = "allow" | "hold" | "block" | "unavailable";
export type Outcome = "ran" | "pending" | "not_run" | "error";

export type ToolResult = {
  tool: string;
  decision: Decision;
  outcome: Outcome;
  content: string;
  reason: string | null;
  plan_id: string | null;
  delegation_id: string | null;
  armoriq_mode: "live" | "disabled";
  latency_ms: number;
};

export type TextReply = {
  call_id: string;
  messages: string[];
  tool_results: ToolResult[];
  pending_holds: string[];
  errors: string[];
};

export type ManagerDecision = "approve" | "reject";

export class AgentError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${AGENT_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // Not JSON (a proxy error page): keep the status text.
    }
    throw new AgentError(detail, res.status);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const agent = {
  /** `typed`: the agent skips read-backs that only guard against misheard speech. */
  open: () =>
    call<{ call_id: string }>("/text/calls", { method: "POST", body: JSON.stringify({ typed: true }) }),

  /** One caller turn. Returns once the agent has replied; a held request keeps waiting. */
  say: (callId: string, text: string) =>
    call<TextReply>(`/text/calls/${callId}/turns`, {
      method: "POST",
      body: JSON.stringify({ text, wait_for_holds: false }),
    }),

  /** Whatever the agent said since the last reply, after any held request is settled. */
  collect: (callId: string) =>
    call<TextReply>(`/text/calls/${callId}/collect`, {
      method: "POST",
      body: JSON.stringify({ wait_for_holds: true }),
    }),

  /** Demo: decide this call's own held request as the manager (sent to ArmorIQ). */
  decide: (callId: string, decision: ManagerDecision) =>
    call<{ tool: string; decision: ManagerDecision; armoriq_status: number }>(
      `/text/calls/${callId}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
    ),

  /** Demo: decide a voice call's own held request (same rules as text calls). */
  decideCall: (callId: string, decision: ManagerDecision) =>
    call<{ tool: string; decision: ManagerDecision; armoriq_status: number }>(
      `/calls/${callId}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
    ),

  hangUp: (callId: string, init?: RequestInit) =>
    call<void>(`/text/calls/${callId}`, { ...init, method: "DELETE" }),
};
