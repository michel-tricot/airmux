export type InferenceSurface = 'oai' | 'oai_compatible' | 'responses' | 'messages';
export type InferenceMessage = { role: 'system' | 'user' | 'assistant'; content: string };
export type InferenceUsage = { inputTokens: number; outputTokens: number; cacheReadTokens: number };
export type InferenceResult = { content: string; usage?: InferenceUsage; finishReason?: string; firstTokenMs?: number; durationMs: number };

export type InferenceRequestOptions = {
  surface: InferenceSurface;
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
  dialect?: string;
  apiKeyHeader: 'Authorization' | 'x-api-key';
};

type ParsedEvent = {
  delta?: string;
  finalContent?: string;
  usage?: InferenceUsage;
  finishReason?: string;
  complete?: boolean;
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

function openAIUsage(value: unknown): InferenceUsage | undefined {
  const usage = objectOf(value);
  if (typeof usage.prompt_tokens !== 'number' || typeof usage.completion_tokens !== 'number') return undefined;
  const details = objectOf(usage.prompt_tokens_details);
  return {
    inputTokens: usage.prompt_tokens,
    outputTokens: usage.completion_tokens,
    cacheReadTokens: typeof details.cached_tokens === 'number' ? details.cached_tokens : 0,
  };
}

function responsesUsage(value: unknown): InferenceUsage | undefined {
  const usage = objectOf(value);
  if (typeof usage.input_tokens !== 'number' || typeof usage.output_tokens !== 'number') return undefined;
  const details = objectOf(usage.input_tokens_details);
  return {
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    cacheReadTokens: typeof details.cached_tokens === 'number' ? details.cached_tokens : 0,
  };
}

function messagesUsage(value: unknown): InferenceUsage | undefined {
  const usage = objectOf(value);
  if (typeof usage.input_tokens !== 'number' || typeof usage.output_tokens !== 'number') return undefined;
  const cacheReadTokens = typeof usage.cache_read_input_tokens === 'number' ? usage.cache_read_input_tokens : 0;
  const cacheWriteTokens = typeof usage.cache_creation_input_tokens === 'number' ? usage.cache_creation_input_tokens : 0;
  return {
    inputTokens: usage.input_tokens + cacheReadTokens + cacheWriteTokens,
    outputTokens: usage.output_tokens,
    cacheReadTokens,
  };
}

function messagesFinishReason(value: unknown): string | undefined {
  const reason = textOf(value);
  if (!reason) return undefined;
  return (
    {
      end_turn: 'stop',
      stop_sequence: 'stop',
      pause_turn: 'stop',
      max_tokens: 'length',
      tool_use: 'tool_calls',
      refusal: 'content_filter',
    }[reason] ?? 'stop'
  );
}

function textParts(value: unknown, textType: string): string {
  return arrayOf(value)
    .map(objectOf)
    .filter((part) => part.type === textType)
    .map((part) => textOf(part.text) ?? '')
    .join('');
}

function canonicalContent(body: Record<string, unknown>): string {
  return textParts(body.content, 'text');
}

function responsesContent(body: Record<string, unknown>): string {
  return arrayOf(body.output)
    .map(objectOf)
    .filter((item) => item.type === 'message')
    .map((item) => textParts(item.content, 'output_text'))
    .join('');
}

function responsesFinishReason(body: Record<string, unknown>): string {
  if (body.status !== 'incomplete') return 'stop';
  return objectOf(body.incomplete_details).reason === 'content_filter' ? 'content_filter' : 'length';
}

function responseMessages(messages: InferenceMessage[]): { instructions?: string; input: Record<string, unknown>[] } {
  const instructions = messages
    .filter((message) => message.role === 'system')
    .map((message) => message.content)
    .join('\n');
  const input = messages
    .filter((message) => message.role !== 'system')
    .map((message) => ({
      role: message.role,
      content: [{ type: message.role === 'assistant' ? 'output_text' : 'input_text', text: message.content }],
    }));
  return { ...(instructions ? { instructions } : {}), input };
}

function messagesBody(messages: InferenceMessage[]): { system?: string; messages: { role: string; content: string }[] } {
  const system = messages
    .filter((message) => message.role === 'system')
    .map((message) => message.content)
    .join('\n');
  const turns = messages.filter((message) => message.role !== 'system').map((message) => ({ role: message.role, content: message.content }));
  return { ...(system ? { system } : {}), messages: turns };
}

export function prepareInferenceRequest(options: InferenceRequestOptions): PreparedInferenceRequest {
  const common = { model: options.model, temperature: options.temperature, stream: options.stream };
  if (options.surface === 'responses') {
    return {
      path: '/inf/v1/responses',
      apiKeyHeader: 'Authorization',
      body: { ...common, ...responseMessages(options.messages), max_output_tokens: options.maxTokens },
    };
  }
  if (options.surface === 'messages') {
    return {
      path: '/inf/v1/messages',
      apiKeyHeader: 'x-api-key',
      body: { ...common, ...messagesBody(options.messages), max_tokens: options.maxTokens },
    };
  }
  if (options.surface === 'oai_compatible') {
    return {
      path: '/inf/v1/chat/completions',
      dialect: 'canonical',
      apiKeyHeader: 'Authorization',
      body: {
        ...common,
        messages: options.messages.map((message) => ({ role: message.role, content: [{ type: 'text', text: message.content }] })),
        max_tokens: options.maxTokens,
      },
    };
  }
  return {
    path: '/inf/v1/chat/completions',
    dialect: 'openai_native',
    apiKeyHeader: 'Authorization',
    body: { ...common, messages: options.messages, max_tokens: options.maxTokens },
  };
}

function parseOpenAIEvent(body: Record<string, unknown>): ParsedEvent {
  const choice = objectOf(arrayOf(body.choices)[0]);
  const delta = objectOf(choice.delta).content;
  if (delta != null && typeof delta !== 'string') throw new Error('The gateway returned invalid streamed content');
  const finishReason = choice.finish_reason;
  if (finishReason != null && typeof finishReason !== 'string') throw new Error('The gateway returned invalid streamed finish reason');
  return {
    delta: textOf(delta),
    usage: openAIUsage(body.usage),
    finishReason: textOf(finishReason),
  };
}

function parseCanonicalEvent(body: Record<string, unknown>): ParsedEvent {
  const delta = objectOf(body.delta);
  return {
    delta: delta.type === 'text' ? textOf(delta.text) : undefined,
    usage: canonicalUsage(body.usage),
    finishReason: textOf(body.finish_reason),
  };
}

function parseResponsesEvent(body: Record<string, unknown>): ParsedEvent {
  if (body.type === 'response.output_text.delta') return { delta: textOf(body.delta) };
  if (body.type !== 'response.completed') return {};
  const response = objectOf(body.response);
  return {
    finalContent: responsesContent(response),
    usage: responsesUsage(response.usage),
    finishReason: responsesFinishReason(response),
    complete: true,
  };
}

function parseMessagesEvent(body: Record<string, unknown>): ParsedEvent {
  if (body.type === 'content_block_delta') {
    const delta = objectOf(body.delta);
    return { delta: delta.type === 'text_delta' ? textOf(delta.text) : undefined };
  }
  if (body.type === 'message_delta') {
    return {
      usage: messagesUsage(body.usage),
      finishReason: messagesFinishReason(objectOf(body.delta).stop_reason),
    };
  }
  return { complete: body.type === 'message_stop' };
}

function parseEvent(surface: InferenceSurface, data: string): ParsedEvent {
  let body: Record<string, unknown>;
  try {
    body = objectOf(JSON.parse(data));
  } catch {
    throw new Error('The gateway returned an invalid streaming event');
  }
  if (body.error) throw new Error(errorMessage(body) ?? 'The gateway stream failed');
  if (surface === 'oai') return parseOpenAIEvent(body);
  if (surface === 'oai_compatible') return parseCanonicalEvent(body);
  if (surface === 'responses') return parseResponsesEvent(body);
  return parseMessagesEvent(body);
}

async function streamedContent(
  response: Response,
  surface: InferenceSurface,
  startedAt: number,
  onDelta?: (content: string) => void,
): Promise<InferenceResult> {
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
    const event = parseEvent(surface, data);
    usage = event.usage ?? usage;
    finishReason = event.finishReason ?? finishReason;
    complete = event.complete ?? complete;
    const nextContent = event.delta != null ? content + event.delta : content || event.finalContent || '';
    if (nextContent !== content) {
      content = nextContent;
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

function bufferedResult(surface: InferenceSurface, body: Record<string, unknown>, durationMs: number): InferenceResult {
  if (surface === 'oai') {
    const choice = objectOf(arrayOf(body.choices)[0]);
    const content = objectOf(choice.message).content;
    if (typeof content !== 'string') throw new Error('The gateway returned an invalid response');
    return { content, usage: openAIUsage(body.usage), finishReason: textOf(choice.finish_reason), durationMs };
  }
  if (surface === 'oai_compatible') {
    return { content: canonicalContent(body), usage: canonicalUsage(body.usage), finishReason: textOf(body.finish_reason), durationMs };
  }
  if (surface === 'responses') {
    return {
      content: responsesContent(body),
      usage: responsesUsage(body.usage),
      finishReason: responsesFinishReason(body),
      durationMs,
    };
  }
  return {
    content: textParts(body.content, 'text'),
    usage: messagesUsage(body.usage),
    finishReason: messagesFinishReason(body.stop_reason),
    durationMs,
  };
}

export async function inferenceCompletion(options: InferenceCompletionOptions): Promise<InferenceResult> {
  const startedAt = performance.now();
  const prepared = prepareInferenceRequest(options);
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'fetch',
    ...(prepared.dialect ? { 'x-airllm-dialect': prepared.dialect } : {}),
  };
  const request = { method: 'POST', headers, body: JSON.stringify(prepared.body), signal: options.signal } satisfies RequestInit;
  let response = await fetch(prepared.path, request);
  for (const delayMs of SESSION_PROPAGATION_DELAYS_MS) {
    if (response.status !== 401) break;
    await response.body?.cancel();
    await wait(delayMs, options.signal);
    response = await fetch(prepared.path, request);
  }
  if (!response.ok) throw await responseError(response);
  if (options.stream) return streamedContent(response, options.surface, startedAt, options.onDelta);
  const body = objectOf(await response.json());
  return bufferedResult(options.surface, body, performance.now() - startedAt);
}
