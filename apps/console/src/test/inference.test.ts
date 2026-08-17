import { afterEach, describe, expect, it, vi } from 'vitest';
import { chatCompletion } from '@/lib/inference';

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
  vi.unstubAllGlobals();
});

describe('chatCompletion', () => {
  it('uses the inference prefix and requests the OpenAI response dialect', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ choices: [{ message: { content: 'hello' } }] }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      chatCompletion({
        token: 'secret',
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        temperature: 0,
        stream: false,
      }),
    ).resolves.toBe('hello');

    expect(fetchMock).toHaveBeenCalledWith(
      '/inf/v1/chat/completions',
      expect.objectContaining({
        method: 'POST',
        headers: {
          Authorization: 'Bearer secret',
          'Content-Type': 'application/json',
          'x-airllm-dialect': 'openai_native',
        },
      }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({ temperature: 0, stream: false });
  });

  it('assembles SSE events split across lines, chunks, and UTF-8 code points', async () => {
    const body = [
      'data: {"choices":[{"delta":{"content":"hé"}}]}\r\n\r\n',
      'data: {"choices":[{"delta":{"content":"llo 🌍"}}]}\n\n',
      'data: [DONE]\n\n',
    ].join('');
    const bytes = encoder.encode(body);
    const globe = body.indexOf('🌍');
    const globeByte = encoder.encode(body.slice(0, globe)).length;
    const chunks = [bytes.slice(0, 11), bytes.slice(11, globeByte + 1), bytes.slice(globeByte + 1)];
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse(chunks)));
    const deltas: string[] = [];

    await expect(
      chatCompletion({
        token: 'secret',
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
        onDelta: (content) => deltas.push(content),
      }),
    ).resolves.toBe('héllo 🌍');
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

    await expect(chatCompletion({ token: 'secret', model: 'model-1', messages: [{ role: 'user', content: 'hi' }], stream: false })).rejects.toThrow(
      '405: Method Not Allowed',
    );
  });
});
