import { afterEach, describe, expect, it, vi } from 'vitest';
import { inferenceCompletion } from '@/lib/inference';

const encoder = new TextEncoder();
const usage = { input_tokens: 7, output_tokens: 3, cache_read_tokens: 2, cache_write_tokens: 0, estimated: false };
const gateway = { adjustments: [] };
const completion = { id: 'reply', model: 'model-1', content: [{ type: 'text', text: 'hello' }], usage, gateway };

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
  it('uses the canonical gateway contract', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        id: 'reply',
        model: 'model-1',
        gateway,
        content: [{ type: 'text', text: 'hello' }],
        finish_reason: 'stop',
        usage,
      }),
    );
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
      'x-tokkeeper-dialect': 'canonical',
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      model: 'model-1',
      messages: [{ role: 'user', content: [{ type: 'text', text: 'hi' }] }],
      temperature: 0,
      stream: false,
    });
  });

  it('assembles canonical SSE events split across lines, chunks, and UTF-8 code points', async () => {
    const body = [
      'data: {"id":"reply","delta":{"type":"text","text":"hé"}}\r\n\r\n',
      'data: {"id":"reply","delta":{"type":"text","text":"llo 🌍"}}\n\n',
      'data: {"id":"reply","finish_reason":"stop","usage":{"input_tokens":7,"output_tokens":3,"cache_read_tokens":2,"cache_write_tokens":0,"estimated":false},"gateway":{"adjustments":[]}}\n\n',
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
      .mockResolvedValueOnce(Response.json({ id: 'reply', model: 'model-1', content: [{ type: 'text', text: 'ready' }], usage, gateway }));
    vi.stubGlobal('fetch', fetchMock);

    const completion = inferenceCompletion({
      model: 'model-1',
      messages: [{ role: 'user', content: 'hi' }],
      stream: false,
    });
    await vi.advanceTimersByTimeAsync(250);

    await expect(completion).resolves.toMatchObject({ content: 'ready' });
  });

  it('surfaces a canonical stream error', async () => {
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
  { ...completion, content: 'hello' },
  { ...completion, content: [{ type: 'text' }] },
  { ...completion, usage: { ...usage, input_tokens: '7' } },
])('rejects malformed canonical responses: %j', async (body) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(Response.json(body)));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: false })).rejects.toThrow('invalid completion response');
});

it.each(['{}', '[]', '{"id":"reply","delta":{"type":"text","text":42}}'])('rejects malformed canonical stream events: %s', async (event) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode(`data: ${event}\n\ndata: [DONE]\n\n`)])));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: true })).rejects.toThrow('invalid streaming event');
});

it.each([
  'data: {"id":"reply","delta":{"type":"text","text":"partial"}}\n\n',
  'data: {"id":"reply","delta":{"type":"text","text":"partial"}}\n\ndata: [DONE]\n\n',
  `data: ${JSON.stringify({ id: 'reply', usage, gateway })}\n\n`,
])('rejects a stream without both its closing event and DONE marker: %s', async (body) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode(body)])));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: true })).rejects.toThrow('incomplete stream');
});

it.each(
  [[], [{ type: 'reasoning', text: 'thinking' }], [{ type: 'tool_call', id: 'call-1', name: 'lookup', arguments: '{}' }]].map((content) => ({
    content,
  })),
)('accepts valid completions without text: $content', async ({ content }) => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...completion, content })));
  await expect(inferenceCompletion({ model: 'model-1', messages: [], stream: false })).resolves.toMatchObject({
    content: '',
    usage: { inputTokens: 7 },
  });
});
