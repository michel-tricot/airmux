import { z } from 'zod';

export type InferenceMessage = { role: 'system' | 'user' | 'assistant'; content: string };
export type InferenceUsage = { inputTokens: number; outputTokens: number; cacheReadTokens: number };
export type InferenceResult = { content: string; usage?: InferenceUsage; finishReason?: string; firstTokenMs?: number; durationMs: number };

export type InferenceRequestOptions = {
  model: string;
  messages: InferenceMessage[];
  temperature?: number;
  maxTokens?: number;
  stream: boolean;
};

type InferenceCompletionOptions = InferenceRequestOptions & {
  signal?: AbortSignal;
  onDelta?: (content: string) => void;
};

export type PreparedInferenceRequest = {
  path: string;
  body: Record<string, unknown>;
};

type ParsedEvent = {
  closing: boolean;
  delta?: string;
  usage?: InferenceUsage;
  finishReason?: string;
};

const SESSION_PROPAGATION_DELAYS_MS = [250, 500, 1_000, 1_500, 2_000];

function objectOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function wait(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(resolve, delayMs);
    signal?.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timeout);
        reject(new DOMException('The operation was aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

function errorMessage(value: unknown): string | null {
  const body = objectOf(value);
  const error = objectOf(body.error);
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  if (typeof error.message === 'string' && error.message.trim()) return error.message;
  if (typeof error.code === 'string' && error.code.trim()) return error.code;
  return null;
}

async function responseError(response: Response): Promise<Error> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('json')) {
    const body = await response.json().catch(() => null);
    const message = errorMessage(body);
    if (message) return new Error(`${response.status}: ${message}`);
  }
  return new Error(`${response.status}: ${response.statusText || 'Request failed'}`);
}

const finishReasonSchema = z.enum(['stop', 'length', 'tool_calls', 'content_filter']);
const usageSchema = z
  .object({
    prompt_tokens: z.number().int(),
    completion_tokens: z.number().int(),
    total_tokens: z.number().int(),
    prompt_tokens_details: z.object({ cached_tokens: z.number().int() }).strict(),
  })
  .strict();
const gatewaySchema = z
  .object({
    finish_reason: finishReasonSchema.optional(),
    adjustments: z.array(z.object({ param: z.string(), action: z.enum(['clamped', 'emulated', 'dropped']), detail: z.string() }).strict()),
  })
  .strict();
const toolCallSchema = z
  .object({
    id: z.string(),
    type: z.literal('function'),
    function: z.object({ name: z.string(), arguments: z.string() }).strict(),
  })
  .strict();
const responseSchema = z
  .object({
    id: z.string(),
    object: z.literal('chat.completion'),
    created: z.number().int(),
    model: z.string(),
    choices: z
      .array(
        z
          .object({
            index: z.number().int(),
            message: z
              .object({
                role: z.literal('assistant'),
                content: z.string().nullable(),
                reasoning_content: z.string().optional(),
                tool_calls: z.array(toolCallSchema).optional(),
              })
              .strict(),
            finish_reason: finishReasonSchema.nullable(),
          })
          .strict(),
      )
      .min(1),
    usage: usageSchema,
    gateway: gatewaySchema,
  })
  .strict();
const toolCallDeltaSchema = z
  .object({
    index: z.number().int().nonnegative(),
    id: z.string().optional(),
    type: z.literal('function').optional(),
    function: z.object({ name: z.string().optional(), arguments: z.string().optional() }).strict().optional(),
  })
  .strict();
const deltaSchema = z
  .object({
    role: z.literal('assistant').optional(),
    content: z.string().nullable().optional(),
    reasoning_content: z.string().optional(),
    tool_calls: z.array(toolCallDeltaSchema).optional(),
  })
  .strict();
const chunkSchema = z
  .object({
    id: z.string(),
    object: z.literal('chat.completion.chunk'),
    created: z.number().int(),
    model: z.string(),
    choices: z.array(z.object({ index: z.number().int(), delta: deltaSchema, finish_reason: finishReasonSchema.nullable().optional() }).strict()),
    usage: usageSchema.optional(),
    gateway: gatewaySchema.optional(),
  })
  .strict();

function openAIUsage(usage: z.infer<typeof usageSchema>): InferenceUsage {
  return {
    inputTokens: usage.prompt_tokens,
    outputTokens: usage.completion_tokens,
    cacheReadTokens: usage.prompt_tokens_details.cached_tokens,
  };
}

export function prepareInferenceRequest(options: InferenceRequestOptions): PreparedInferenceRequest {
  return {
    path: '/inf/v1/chat/completions',
    body: {
      model: options.model,
      messages: options.messages,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
      stream: options.stream,
    },
  };
}

function parseEvent(data: string): ParsedEvent {
  let body: Record<string, unknown>;
  try {
    body = objectOf(JSON.parse(data));
  } catch {
    throw new Error('The gateway returned an invalid streaming event');
  }
  if (body.error) throw new Error(errorMessage(body) ?? 'The gateway stream failed');
  const parsed = chunkSchema.safeParse(body);
  if (!parsed.success) throw new Error('The gateway returned an invalid streaming event');
  const event = parsed.data;
  const choice = event.choices[0];
  return {
    closing: event.choices.length === 0 && event.usage !== undefined && event.gateway !== undefined,
    delta: choice?.delta.content ?? undefined,
    usage: event.usage ? openAIUsage(event.usage) : undefined,
    finishReason: choice?.finish_reason ?? event.gateway?.finish_reason,
  };
}

async function streamedContent(response: Response, startedAt: number, onDelta?: (content: string) => void): Promise<InferenceResult> {
  if (!response.body) throw new Error('The gateway returned an empty stream');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let dataLines: string[] = [];
  let content = '';
  let usage: InferenceUsage | undefined;
  let finishReason: string | undefined;
  let firstTokenMs: number | undefined;
  let complete = false;
  let closing = false;

  const dispatch = () => {
    if (dataLines.length === 0) return;
    const data = dataLines.join('\n');
    dataLines = [];
    if (data === '[DONE]') {
      if (!closing) throw new Error('The gateway returned an incomplete stream');
      complete = true;
      return;
    }
    const event = parseEvent(data);
    closing = event.closing;
    usage = event.usage ?? usage;
    finishReason = event.finishReason ?? finishReason;
    if (event.delta !== undefined) {
      content += event.delta;
      firstTokenMs ??= performance.now() - startedAt;
      onDelta?.(content);
    }
  };

  const consume = (line: string) => {
    if (line === '') {
      dispatch();
      return;
    }
    if (line.startsWith(':') || line.startsWith('event:')) return;
    if (line === 'data') dataLines.push('');
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
  };

  try {
    while (!complete) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split(/\r\n|\r|\n/);
      pending = done ? '' : (lines.pop() ?? '');
      for (const line of lines) {
        consume(line);
        if (complete) break;
      }
      if (done) {
        if (pending) consume(pending);
        dispatch();
        break;
      }
    }
    if (!complete) throw new Error('The gateway returned an incomplete stream');
  } finally {
    void reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  return { content, usage, finishReason, firstTokenMs, durationMs: performance.now() - startedAt };
}

function bufferedResult(body: unknown, durationMs: number): InferenceResult {
  const parsed = responseSchema.safeParse(body);
  if (!parsed.success) throw new Error('The gateway returned an invalid completion response');
  const response = parsed.data;
  const choice = response.choices[0];
  return {
    content: choice.message.content ?? '',
    usage: openAIUsage(response.usage),
    finishReason: choice.finish_reason ?? undefined,
    durationMs,
  };
}

export async function inferenceCompletion(options: InferenceCompletionOptions): Promise<InferenceResult> {
  const startedAt = performance.now();
  const prepared = prepareInferenceRequest(options);
  const request = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'fetch',
    },
    body: JSON.stringify(prepared.body),
    signal: options.signal,
  } satisfies RequestInit;
  let response = await fetch(prepared.path, request);
  for (const delayMs of SESSION_PROPAGATION_DELAYS_MS) {
    if (response.status !== 401) break;
    await response.body?.cancel();
    await wait(delayMs, options.signal);
    response = await fetch(prepared.path, request);
  }
  if (!response.ok) throw await responseError(response);
  if (options.stream) return streamedContent(response, startedAt, options.onDelta);
  const body: unknown = await response.json().catch(() => {
    throw new Error('The gateway returned an invalid completion response');
  });
  return bufferedResult(body, performance.now() - startedAt);
}
