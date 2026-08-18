export type InferenceMessage = { role: 'system' | 'user' | 'assistant'; content: string };
export type InferenceUsage = { inputTokens: number; outputTokens: number; cacheReadTokens: number };
export type ChatCompletionResult = { content: string; usage?: InferenceUsage; finishReason?: string; firstTokenMs?: number; durationMs: number };

type ChatCompletionOptions = {
  model: string;
  messages: InferenceMessage[];
  temperature?: number;
  maxTokens?: number;
  stream: boolean;
  signal?: AbortSignal;
  onDelta?: (content: string) => void;
};

type OpenAIChunk = {
  choices?: { delta?: { content?: unknown }; finish_reason?: unknown }[];
  usage?: { prompt_tokens?: unknown; completion_tokens?: unknown; prompt_tokens_details?: { cached_tokens?: unknown } };
  error?: { message?: unknown; code?: unknown };
};

const SESSION_PROPAGATION_DELAYS_MS = [250, 500, 1_000, 1_500, 2_000];

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
  if (!value || typeof value !== 'object') return null;
  const body = value as { detail?: unknown; error?: { message?: unknown; code?: unknown } };
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  if (typeof body.error?.message === 'string' && body.error.message.trim()) return body.error.message;
  if (typeof body.error?.code === 'string' && body.error.code.trim()) return body.error.code;
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

function usageOf(value: OpenAIChunk['usage']): InferenceUsage | undefined {
  if (!value || typeof value.prompt_tokens !== 'number' || typeof value.completion_tokens !== 'number') return undefined;
  return {
    inputTokens: value.prompt_tokens,
    outputTokens: value.completion_tokens,
    cacheReadTokens: typeof value.prompt_tokens_details?.cached_tokens === 'number' ? value.prompt_tokens_details.cached_tokens : 0,
  };
}

function parseChunk(data: string): { content?: string; usage?: InferenceUsage; finishReason?: string } {
  let chunk: OpenAIChunk;
  try {
    chunk = JSON.parse(data) as OpenAIChunk;
  } catch {
    throw new Error('The gateway returned an invalid streaming event');
  }
  if (chunk.error) throw new Error(errorMessage(chunk) ?? 'The gateway stream failed');
  const content = chunk.choices?.[0]?.delta?.content;
  if (content != null && typeof content !== 'string') throw new Error('The gateway returned invalid streamed content');
  const finishReason = chunk.choices?.[0]?.finish_reason;
  if (finishReason != null && typeof finishReason !== 'string') throw new Error('The gateway returned invalid streamed finish reason');
  return {
    content: typeof content === 'string' ? content : undefined,
    usage: usageOf(chunk.usage),
    finishReason: typeof finishReason === 'string' ? finishReason : undefined,
  };
}

async function streamedContent(response: Response, startedAt: number, onDelta?: (content: string) => void): Promise<ChatCompletionResult> {
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
    const chunk = parseChunk(data);
    usage = chunk.usage ?? usage;
    finishReason = chunk.finishReason ?? finishReason;
    if (chunk.content != null) {
      content += chunk.content;
      firstTokenMs ??= performance.now() - startedAt;
      onDelta?.(content);
    }
  };

  const consume = (line: string) => {
    if (line === '') {
      dispatch();
      return;
    }
    if (line.startsWith(':')) return;
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

export async function chatCompletion(options: ChatCompletionOptions): Promise<ChatCompletionResult> {
  const startedAt = performance.now();
  const request = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'fetch',
      'x-airllm-dialect': 'openai_native',
    },
    body: JSON.stringify({
      model: options.model,
      messages: options.messages,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
      stream: options.stream,
    }),
    signal: options.signal,
  } satisfies RequestInit;
  let response = await fetch('/inf/v1/chat/completions', request);
  for (const delayMs of SESSION_PROPAGATION_DELAYS_MS) {
    if (response.status !== 401) break;
    await response.body?.cancel();
    await wait(delayMs, options.signal);
    response = await fetch('/inf/v1/chat/completions', request);
  }
  if (!response.ok) throw await responseError(response);
  if (options.stream) return streamedContent(response, startedAt, options.onDelta);

  const body = (await response.json()) as OpenAIChunk & { choices?: { message?: { content?: unknown }; finish_reason?: unknown }[] };
  const content = body.choices?.[0]?.message?.content;
  if (typeof content !== 'string') throw new Error('The gateway returned an invalid response');
  const finishReason = body.choices?.[0]?.finish_reason;
  if (finishReason != null && typeof finishReason !== 'string') throw new Error('The gateway returned an invalid finish reason');
  return {
    content,
    usage: usageOf(body.usage),
    finishReason: typeof finishReason === 'string' ? finishReason : undefined,
    durationMs: performance.now() - startedAt,
  };
}
