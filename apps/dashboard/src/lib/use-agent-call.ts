"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { agent, AgentError, type ManagerDecision, type ToolResult } from "@/lib/agent";

export type Line = { id: number; who: "caller" | "agent" | "note"; text: string };
export type Logged = ToolResult & { id: number; at: number };

export type CallStatus =
  | "idle" // no call yet
  | "connecting" // opening the call (the bridge starts an ArmorIQ session, ~10 s)
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
  const [status, setStatus] = useState<CallStatus>("connecting");
  const [held, setHeld] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const callId = useRef<string | null>(null);
  const opening = useRef<Promise<string> | null>(null);
  // Set synchronously: React state updates too late to stop a quick double-click
  // from sending the same line twice (seen live).
  const sending = useRef(false);
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

  /** The open call, opening one if needed; concurrent callers share one request. */
  const ensureCall = useCallback(async () => {
    if (callId.current) return callId.current;
    opening.current ??= agent.open().then(({ call_id }) => {
      callId.current = call_id;
      return call_id;
    });
    try {
      return await opening.current;
    } finally {
      opening.current = null;
    }
  }, []);

  /** Open the call ahead of the first message, so the ArmorIQ session is ready by then. */
  const connect = useCallback(async () => {
    setStatus("connecting");
    try {
      await ensureCall();
      setStatus("ready");
    } catch (e) {
      fail(e);
    }
  }, [ensureCall, fail]);

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
      if (status === "connecting" || sending.current) return;
      sending.current = true;
      setError(null);
      push("caller", [trimmed]);
      setStatus("thinking");
      try {
        const id = await ensureCall();
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
      } finally {
        sending.current = false;
      }
    },
    [status, push, record, fail, awaitOutcome, ensureCall],
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
    void connect();
  }, [connect]);

  // Open the call as the page loads (status starts at "connecting").
  useEffect(() => {
    let live = true;
    ensureCall()
      .then(() => live && setStatus((s) => (s === "connecting" ? "ready" : s)))
      .catch((e: unknown) => live && fail(e));
    return () => {
      live = false;
    };
  }, [ensureCall, fail]);

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
