/**
 * useAgentRunner: React hook that runs a TypeScript agent in the browser
 * and exposes its state for the inspector.
 *
 *   Component
 *     |
 *     +-- useAgentRunner("s01", apiKey)
 *     |     |
 *     |     +-- state: AgentState     --> Inspector panel
 *     |     +-- events: AgentEvent[]  --> Event log
 *     |     +-- isRunning: boolean    --> UI controls
 *     |     +-- sendMessage(text)     --> Start agent loop
 *     |     +-- abort()               --> Stop agent
 *     |     +-- reset()               --> Clear state
 *     |
 *     +-- renders Inspector + Chat UI
 */

import { useState, useCallback, useRef } from "react";
import type { AgentState, AgentEvent, AgentConfig } from "@/agents/shared";

type SessionId =
  | "s01" | "s02" | "s03" | "s04" | "s05"
  | "s06" | "s07" | "s08" | "s09" | "s10"
  | "s11";

async function loadAgent(session: SessionId) {
  switch (session) {
    case "s01": return (await import("@/agents/s01")).AgentLoopAgent;
    case "s02": return (await import("@/agents/s02")).MultiToolAgent;
    case "s03": return (await import("@/agents/s03")).TodoAgent;
    case "s04": return (await import("@/agents/s04")).SubagentAgent;
    case "s05": return (await import("@/agents/s05")).SkillsAgent;
    case "s06": return (await import("@/agents/s06")).CompressionAgent;
    case "s07": return (await import("@/agents/s07")).TasksAgent;
    case "s08": return (await import("@/agents/s08")).BackgroundAgent;
    case "s09": return (await import("@/agents/s09")).TeamMessagingAgent;
    case "s10": return (await import("@/agents/s10")).TeamProtocolsAgent;
    case "s11": return (await import("@/agents/s11")).AutonomousAgent;
    default: throw new Error(`Unknown session: ${session}`);
  }
}

const INITIAL_STATE: AgentState = {
  messages: [],
  tools: [],
  loopIteration: 0,
  stopReason: null,
  totalInputTokens: 0,
  totalOutputTokens: 0,
};

export interface AgentRunnerResult {
  state: AgentState;
  events: AgentEvent[];
  isRunning: boolean;
  error: string | null;
  sendMessage: (text: string) => Promise<void>;
  abort: () => void;
  reset: () => void;
}

export function useAgentRunner(session: SessionId, apiKey: string): AgentRunnerResult {
  const [state, setState] = useState<AgentState>(INITIAL_STATE);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const agentRef = useRef<{ abort: () => void } | null>(null);

  const sendMessage = useCallback(async (text: string) => {
    if (!apiKey) {
      setError("API key required");
      return;
    }

    setIsRunning(true);
    setError(null);

    try {
      const AgentClass = await loadAgent(session);

      const config: AgentConfig = {
        apiKey,
        maxIterations: 10,
        onEvent: (event: AgentEvent) => {
          setEvents((prev) => [...prev, event]);
          if (event.type === "state_change" && event.data) {
            setState(event.data as AgentState);
          }
        },
      };

      const agent = new AgentClass(config);
      agentRef.current = agent;

      setState(agent.getState());

      await agent.run(text);
      setState(agent.getState());
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsRunning(false);
      agentRef.current = null;
    }
  }, [session, apiKey]);

  const abort = useCallback(() => {
    agentRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setState(INITIAL_STATE);
    setEvents([]);
    setError(null);
    setIsRunning(false);
    agentRef.current = null;
  }, []);

  return { state, events, isRunning, error, sendMessage, abort, reset };
}
