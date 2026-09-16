import { afterEach, describe, expect, it, vi } from 'vitest';
import { inferenceCompletion } from '@/lib/inference';

const encoder = new TextEncoder();
const usage = { prompt_tokens: 7, completion_tokens: 3, total_tokens: 10, prompt_tokens_details: { cached_tokens: 2 } };
const gateway = { adjustments: [] };
const completion = {
  id: 'reply',
  object: 'chat.completion',
  created: 1,
  model: 'model-1',
  choices: [{ index: 0, message: { role: 'assistant', content: 'hello' }, finish_reason: 'stop' }],
  usage,
  gateway,
};

function streamResponse(chunks: Uint8Array[]) {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    }),
    { headers: { 'content-type': 'text/event-stream' } },
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('inferenceCompletion', () => {
  it('uses the OpenAI Chat Completions contract', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json(completion));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      inferenceCompletion({
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        temperature: 0,
        stream: false,
      }),
    ).resolves.toMatchObject({
      content: 'hello',
      usage: { inputTokens: 7, outputTokens: 3, cacheReadTokens: 2 },
      finishReason: 'stop',
    });

    expect(Object.fromEntries(new Headers(fetchMock.mock.calls[0]?.[1]?.headers))).toEqual({
      'content-type': 'application/json',
      'x-requested-with': 'fetch',
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      model: 'model-1',
      messages: [{ role: 'user', content: 'hi' }],
      temperature: 0,
      stream: false,
    });
  });

  it('accepts output-limit adjustments from the gateway', async () => {
    const adjusted = {
      ...completion,
      gateway: {
        adjustments: [{ param: 'max_output_tokens', action: 'defaulted', detail: 'model caps output at 4096 tokens', source: 'model' }],
      },
    };
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(Response.json(adjusted)));

    await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: false })).resolves.toMatchObject({ content: 'hello' });
  });

  it('assembles OpenAI SSE events split across lines, chunks, and UTF-8 code points', async () => {
    const body = [
      'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"hé"}}]}\r\n\r\n',
      'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"llo 🌍"},"finish_reason":"stop"}]}\n\n',
      'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[],"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10,"prompt_tokens_details":{"cached_tokens":2}},"gateway":{"adjustments":[]}}\n\n',
      'data: [DONE]\n\n',
    ].join('');
    const bytes = encoder.encode(body);
    const globe = body.indexOf('🌍');
    const globeByte = encoder.encode(body.slice(0, globe)).length;
    const chunks = [bytes.slice(0, 11), bytes.slice(11, globeByte + 1), bytes.slice(globeByte + 1)];
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse(chunks)));
    const deltas: string[] = [];

    await expect(
      inferenceCompletion({
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
        onDelta: (content) => deltas.push(content),
      }),
    ).resolves.toMatchObject({
      content: 'héllo 🌍',
      usage: { inputTokens: 7, outputTokens: 3, cacheReadTokens: 2 },
      finishReason: 'stop',
    });
    expect(deltas).toEqual(['hé', 'héllo 🌍']);
  });

  it('returns a concise error instead of rendering an HTML proxy body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response('<html><h1>405 Not Allowed</h1></html>', {
          status: 405,
          statusText: 'Method Not Allowed',
          headers: { 'content-type': 'text/html' },
        }),
      ),
    );

    await expect(inferenceCompletion({ model: 'model-1', messages: [{ role: 'user', content: 'hi' }], stream: false })).rejects.toThrow(
      '405: Method Not Allowed',
    );
  });

  it('waits for a newly published playground session to reach the data plane', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ error: { code: 'invalid_token' } }, { status: 401 }))
      .mockResolvedValueOnce(
        Response.json({
          ...completion,
          choices: [{ index: 0, message: { role: 'assistant', content: 'ready' }, finish_reason: 'stop' }],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = inferenceCompletion({
      model: 'model-1',
      messages: [{ role: 'user', content: 'hi' }],
      stream: false,
    });
    await vi.advanceTimersByTimeAsync(250);

    await expect(result).resolves.toMatchObject({ content: 'ready' });
  });

  it('surfaces an OpenAI stream error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode('data: {"error":{"message":"provider unavailable"}}\n\n')])),
    );

    await expect(inferenceCompletion({ model: 'model-1', messages: [{ role: 'user', content: 'hi' }], stream: true })).rejects.toThrow(
      'provider unavailable',
    );
  });
});

it.each([
  null,
  [],
  {},
  { ...completion, choices: [] },
  { ...completion, choices: [{ index: 0, message: { role: 'assistant' }, finish_reason: 'stop' }] },
  { ...completion, usage: { ...usage, prompt_tokens: '7' } },
])('rejects malformed OpenAI responses: %j', async (body) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(Response.json(body)));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: false })).rejects.toThrow('invalid completion response');
});

it.each(['{}', '[]', '{"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":42}}]}'])(
  'rejects malformed OpenAI stream events: %s',
  async (event) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode(`data: ${event}\n\ndata: [DONE]\n\n`)])));
    await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: true })).rejects.toThrow('invalid streaming event');
  },
);

it.each([
  'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n',
  'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"partial"}}]}\n\ndata: [DONE]\n\n',
  `data: ${JSON.stringify({ id: 'reply', object: 'chat.completion.chunk', created: 1, model: 'model-1', choices: [], usage, gateway })}\n\n`,
])('rejects a stream without both its closing event and DONE marker: %s', async (body) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode(body)])));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: true })).rejects.toThrow('incomplete stream');
});

it.each([
  { role: 'assistant', content: null },
  { role: 'assistant', content: null, reasoning_content: 'thinking' },
  { role: 'assistant', content: null, tool_calls: [{ id: 'call-1', type: 'function', function: { name: 'lookup', arguments: '{}' } }] },
])('accepts valid completions without text: $message', async (message) => {
  const choices = [{ index: 0, message, finish_reason: 'stop' }];
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...completion, choices })));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: false })).resolves.toMatchObject({
    content: '',
    usage: { inputTokens: 7 },
  });
});
