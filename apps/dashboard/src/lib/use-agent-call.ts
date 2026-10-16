"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { agent, AgentError, type ManagerDecision, type ToolResult } from "@/lib/agent";

export type Line = { id: number; who: "caller" | "agent" | "note"; text: string };
export type Logged = ToolResult & { id: number; at: number };

export type CallStatus =
  | "idle" // no call yet
  | "thinking" // a turn is in flight
  | "held" // a request is waiting for the manager
  | "deciding" // the manager's decision is on its way to ArmorIQ
  | "ready" // waiting for the caller
  | "error";

/**
 * One text call with the deployed agent. Every reply's tool results become decision log rows;
 * a held request flips the call to "held" and a background collect waits for its outcome,
 * which arrives once the manager (the visitor) decides, or after the hold times out.
 */
export function useAgentCall() {
  const [lines, setLines] = useState<Line[]>([]);
  const [log, setLog] = useState<Logged[]>([]);
  const [status, setStatus] = useState<CallStatus>("idle");
  const [held, setHeld] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const callId = useRef<string | null>(null);
  const nextId = useRef(0);

  const push = useCallback((who: Line["who"], texts: string[]) => {
    if (!texts.length) return;
    setLines((prev) => [...prev, ...texts.map((text) => ({ id: nextId.current++, who, text }))]);
  }, []);

  const record = useCallback((results: ToolResult[]) => {
    if (!results.length) return;
    const now = Date.now();
    setLog((prev) => [...prev, ...results.map((r) => ({ ...r, id: nextId.current++, at: now }))]);
  }, []);

  const fail = useCallback((e: unknown) => {
    const busy = e instanceof AgentError && (e.status === 429 || e.status === 503);
    setError(
      busy
        ? "The agent is busy right now. Please try again in a minute."
        : "Couldn't reach the agent. Check your connection and try again.",
    );
    setStatus("error");
  }, []);

  const awaitOutcome = useCallback(
    async (id: string) => {
      try {
        const reply = await agent.collect(id);
        push("agent", reply.messages);
        record(reply.tool_results);
        setHeld(null);
        setStatus("ready");
      } catch (e) {
        fail(e);
      }
    },
    [push, record, fail],
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || status === "thinking" || status === "held" || status === "deciding") return;
      setError(null);
      push("caller", [trimmed]);
      setStatus("thinking");
      try {
        if (!callId.current) callId.current = (await agent.open()).call_id;
        const id = callId.current;
        const reply = await agent.say(id, trimmed);
        push("agent", reply.messages);
        record(reply.tool_results);
        if (reply.pending_holds.length) {
          setHeld(reply.pending_holds[0]);
          setStatus("held");
          void awaitOutcome(id);
        } else {
          setStatus("ready");
        }
      } catch (e) {
        fail(e);
      }
    },
    [status, push, record, fail, awaitOutcome],
  );

  const decide = useCallback(
    async (decision: ManagerDecision) => {
      const id = callId.current;
      if (!id || status !== "held") return;
      setStatus("deciding");
      try {
        await agent.decide(id, decision);
        push("note", [decision === "approve" ? "You approved it in ArmorIQ." : "You rejected it in ArmorIQ."]);
      } catch (e) {
        // The hold may already have timed out, or ArmorIQ refused: the outcome still arrives.
        push("note", [
          e instanceof AgentError && e.status === 409
            ? "That request was already settled."
            : "ArmorIQ didn't accept the decision; the request will time out safely.",
        ]);
      }
    },
    [status, push],
  );

  const reset = useCallback(() => {
    const id = callId.current;
    callId.current = null;
    if (id) void agent.hangUp(id).catch(() => undefined);
    setLines([]);
    setLog([]);
    setHeld(null);
    setError(null);
    setStatus("idle");
  }, []);

  // Hang up when the visitor leaves, so held requests are cancelled server-side.
  useEffect(() => {
    const end = () => {
      // keepalive lets the request outlive the page.
      if (callId.current) void agent.hangUp(callId.current, { keepalive: true }).catch(() => undefined);
    };
    window.addEventListener("pagehide", end);
    return () => window.removeEventListener("pagehide", end);
  }, []);

  return { lines, log, status, held, error, send, decide, reset };
}
