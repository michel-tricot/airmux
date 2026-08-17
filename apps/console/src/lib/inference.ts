export type InferenceMessage = { role: 'system' | 'user' | 'assistant'; content: string };

type ChatCompletionOptions = {
  token: string;
  model: string;
  messages: InferenceMessage[];
  temperature?: number;
  maxTokens?: number;
  stream: boolean;
  signal?: AbortSignal;
  onDelta?: (content: string) => void;
};

type OpenAIChunk = {
  choices?: { delta?: { content?: unknown } }[];
  error?: { message?: unknown; code?: unknown };
};

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

function parseChunk(data: string): string | null {
  let chunk: OpenAIChunk;
  try {
    chunk = JSON.parse(data) as OpenAIChunk;
  } catch {
    throw new Error('The gateway returned an invalid streaming event');
  }
  if (chunk.error) throw new Error(errorMessage(chunk) ?? 'The gateway stream failed');
  const content = chunk.choices?.[0]?.delta?.content;
  if (content == null) return null;
  if (typeof content !== 'string') throw new Error('The gateway returned invalid streamed content');
  return content;
}

async function streamedContent(response: Response, onDelta?: (content: string) => void): Promise<string> {
  if (!response.body) throw new Error('The gateway returned an empty stream');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let dataLines: string[] = [];
  let content = '';
  let complete = false;

  const dispatch = () => {
    if (dataLines.length === 0) return;
    const data = dataLines.join('\n');
    dataLines = [];
    if (data === '[DONE]') {
      complete = true;
      return;
    }
    const delta = parseChunk(data);
    if (delta != null) {
      content += delta;
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
  return content;
}

export async function chatCompletion(options: ChatCompletionOptions): Promise<string> {
  const response = await fetch('/inf/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${options.token}`,
      'Content-Type': 'application/json',
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
  });
  if (!response.ok) throw await responseError(response);
  if (options.stream) return streamedContent(response, options.onDelta);

  const body = (await response.json()) as { choices?: { message?: { content?: unknown } }[] };
  const content = body.choices?.[0]?.message?.content;
  if (typeof content !== 'string') throw new Error('The gateway returned an invalid response');
  return content;
}
