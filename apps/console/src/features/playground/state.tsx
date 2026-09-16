import { createContext, useContext, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import type { InferenceMessage } from '@/lib/inference';

export type PlaygroundRequest = {
  model: string;
  messages: InferenceMessage[];
  temperature: number | undefined;
  maxTokens: number | undefined;
  stream: boolean;
};

export type PlaygroundInteraction = {
  model: string;
  provider: string | undefined;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  estimatedCostPicoUsd: bigint;
  durationMs: number;
  firstTokenMs: number | undefined;
};

export type PlaygroundMessage = {
  role: 'user' | 'assistant';
  content: string;
  finishReason?: string;
  interaction?: PlaygroundInteraction;
  request?: PlaygroundRequest;
};

export type PlaygroundState = {
  selectedModel: string;
  systemPrompt: string;
  temperature: string;
  maxTokens: string;
  streamEnabled: boolean;
  messages: PlaygroundMessage[];
  input: string;
  sessionExpiresAt: string | null;
};

const initialState: PlaygroundState = {
  selectedModel: '',
  systemPrompt: '',
  temperature: '1',
  maxTokens: '',
  streamEnabled: true,
  messages: [],
  input: '',
  sessionExpiresAt: null,
};

type PlaygroundStateContextValue = {
  states: Record<string, PlaygroundState>;
  setStates: Dispatch<SetStateAction<Record<string, PlaygroundState>>>;
};

const PlaygroundStateContext = createContext<PlaygroundStateContextValue | null>(null);

export function PlaygroundProvider({ children }: { children: ReactNode }) {
  const [states, setStates] = useState<Record<string, PlaygroundState>>({});
  return <PlaygroundStateContext.Provider value={{ states, setStates }}>{children}</PlaygroundStateContext.Provider>;
}

export function usePlaygroundState(workspaceKey: string): [PlaygroundState, Dispatch<SetStateAction<PlaygroundState>>] {
  const context = useContext(PlaygroundStateContext);
  if (!context) throw new Error('PlaygroundProvider is required');
  const state = context.states[workspaceKey] ?? initialState;
  const setState: Dispatch<SetStateAction<PlaygroundState>> = (update) => {
    context.setStates((states) => {
      const current = states[workspaceKey] ?? initialState;
      return { ...states, [workspaceKey]: typeof update === 'function' ? update(current) : update };
    });
  };
  return [state, setState];
}
