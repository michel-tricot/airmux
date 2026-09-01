import { afterEach, describe, expect, it, vi } from 'vitest';
import { inferenceCompletion } from '@/lib/inference';

const encoder = new TextEncoder();

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
        content: [{ type: 'text', text: 'hello' }],
        finish_reason: 'stop',
        usage: { input_tokens: 7, output_tokens: 3, cache_read_tokens: 2 },
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

    expect(fetchMock).toHaveBeenCalledWith(
      '/inf/v1/chat/completions',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'fetch',
          'x-airllm-dialect': 'canonical',
        },
      }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      model: 'model-1',
      messages: [{ role: 'user', content: [{ type: 'text', text: 'hi' }] }],
      temperature: 0,
      stream: false,
    });
  });

  it('assembles canonical SSE events split across lines, chunks, and UTF-8 code points', async () => {
    const body = [
      'data: {"delta":{"type":"text","text":"hé"}}\r\n\r\n',
      'data: {"delta":{"type":"text","text":"llo 🌍"}}\n\n',
      'data: {"finish_reason":"stop","usage":{"input_tokens":7,"output_tokens":3,"cache_read_tokens":2}}\n\n',
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
      .mockResolvedValueOnce(Response.json({ content: [{ type: 'text', text: 'ready' }] }));
    vi.stubGlobal('fetch', fetchMock);

    const completion = inferenceCompletion({
      model: 'model-1',
      messages: [{ role: 'user', content: 'hi' }],
      stream: false,
    });
    await vi.advanceTimersByTimeAsync(250);

    await expect(completion).resolves.toMatchObject({ content: 'ready' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
