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
  dialect: 'canonical';
};

type ParsedEvent = {
  delta?: string;
  usage?: InferenceUsage;
  finishReason?: string;
};

const SESSION_PROPAGATION_DELAYS_MS = [250, 500, 1_000, 1_500, 2_000];

function objectOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textOf(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
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

function canonicalUsage(value: unknown): InferenceUsage | undefined {
  const usage = objectOf(value);
  if (typeof usage.input_tokens !== 'number' || typeof usage.output_tokens !== 'number') return undefined;
  return {
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    cacheReadTokens: typeof usage.cache_read_tokens === 'number' ? usage.cache_read_tokens : 0,
  };
}

function textParts(value: unknown): string {
  return arrayOf(value)
    .map(objectOf)
    .filter((part) => part.type === 'text')
    .map((part) => textOf(part.text) ?? '')
    .join('');
}

export function prepareInferenceRequest(options: InferenceRequestOptions): PreparedInferenceRequest {
  return {
    path: '/inf/v1/chat/completions',
    dialect: 'canonical',
    body: {
      model: options.model,
      messages: options.messages.map((message) => ({ role: message.role, content: [{ type: 'text', text: message.content }] })),
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
  const delta = objectOf(body.delta);
  return {
    delta: delta.type === 'text' ? textOf(delta.text) : undefined,
    usage: canonicalUsage(body.usage),
    finishReason: textOf(body.finish_reason),
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

  const dispatch = () => {
    if (dataLines.length === 0) return;
    const data = dataLines.join('\n');
    dataLines = [];
    if (data === '[DONE]') {
      complete = true;
      return;
    }
    const event = parseEvent(data);
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
  return { content, usage, finishReason, firstTokenMs, durationMs: performance.now() - startedAt };
}

function bufferedResult(body: Record<string, unknown>, durationMs: number): InferenceResult {
  return {
    content: textParts(body.content),
    usage: canonicalUsage(body.usage),
    finishReason: textOf(body.finish_reason),
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
      'x-airllm-dialect': prepared.dialect,
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
  return bufferedResult(objectOf(await response.json()), performance.now() - startedAt);
}
