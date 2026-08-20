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
  it('uses the inference prefix and requests the OpenAI response dialect', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        choices: [{ message: { content: 'hello' }, finish_reason: 'stop' }],
        usage: { prompt_tokens: 7, completion_tokens: 3, prompt_tokens_details: { cached_tokens: 2 } },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      inferenceCompletion({
        surface: 'oai',
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
      'data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":3}}\n\n',
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
        surface: 'oai',
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        stream: true,
        onDelta: (content) => deltas.push(content),
      }),
    ).resolves.toMatchObject({ content: 'héllo 🌍', usage: { inputTokens: 7, outputTokens: 3 }, finishReason: 'stop' });
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

    await expect(
      inferenceCompletion({ surface: 'oai', model: 'model-1', messages: [{ role: 'user', content: 'hi' }], stream: false }),
    ).rejects.toThrow('405: Method Not Allowed');
  });

  it('waits for a newly published playground session to reach the data plane', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ error: { code: 'invalid_token' } }, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ choices: [{ message: { content: 'ready' } }] }));
    vi.stubGlobal('fetch', fetchMock);

    const completion = inferenceCompletion({
      surface: 'oai',
      model: 'model-1',
      messages: [{ role: 'user', content: 'hi' }],
      stream: false,
    });
    await vi.advanceTimersByTimeAsync(250);

    await expect(completion).resolves.toMatchObject({ content: 'ready' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    {
      surface: 'oai_compatible' as const,
      path: '/inf/v1/chat/completions',
      dialect: 'canonical',
      response: {
        content: [{ type: 'text', text: 'canonical answer' }],
        finish_reason: 'stop',
        usage: { input_tokens: 11, output_tokens: 4, cache_read_tokens: 3 },
      },
      expectedContent: 'canonical answer',
      expectedBody: {
        messages: [
          { role: 'system', content: [{ type: 'text', text: 'be concise' }] },
          { role: 'user', content: [{ type: 'text', text: 'hi' }] },
        ],
        max_tokens: 128,
      },
    },
    {
      surface: 'responses' as const,
      path: '/inf/v1/responses',
      dialect: undefined,
      response: {
        status: 'completed',
        output: [{ type: 'message', content: [{ type: 'output_text', text: 'responses answer' }] }],
        usage: { input_tokens: 11, output_tokens: 4, input_tokens_details: { cached_tokens: 3 } },
      },
      expectedContent: 'responses answer',
      expectedBody: {
        instructions: 'be concise',
        input: [{ role: 'user', content: [{ type: 'input_text', text: 'hi' }] }],
        max_output_tokens: 128,
      },
    },
    {
      surface: 'messages' as const,
      path: '/inf/v1/messages',
      dialect: undefined,
      response: {
        content: [{ type: 'text', text: 'messages answer' }],
        stop_reason: 'end_turn',
        usage: { input_tokens: 6, output_tokens: 4, cache_read_input_tokens: 3, cache_creation_input_tokens: 2 },
      },
      expectedContent: 'messages answer',
      expectedBody: {
        system: 'be concise',
        messages: [{ role: 'user', content: 'hi' }],
        max_tokens: 128,
      },
    },
  ])('routes and normalizes buffered $surface requests', async ({ surface, path, dialect, response, expectedContent, expectedBody }) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      inferenceCompletion({
        surface,
        model: 'model-1',
        messages: [
          { role: 'system', content: 'be concise' },
          { role: 'user', content: 'hi' },
        ],
        temperature: 0.5,
        maxTokens: 128,
        stream: false,
      }),
    ).resolves.toMatchObject({
      content: expectedContent,
      usage: { inputTokens: 11, outputTokens: 4, cacheReadTokens: 3 },
      finishReason: 'stop',
    });

    expect(fetchMock).toHaveBeenCalledWith(path, expect.anything());
    const request = fetchMock.mock.calls[0]?.[1];
    expect((request?.headers as Record<string, string>)['x-airllm-dialect']).toBe(dialect);
    expect(JSON.parse(String(request?.body))).toMatchObject(expectedBody);
  });

  it.each([
    {
      surface: 'oai_compatible' as const,
      body: [
        'data: {"delta":{"type":"text","text":"canonical stream"}}',
        '',
        'data: {"finish_reason":"stop","usage":{"input_tokens":7,"output_tokens":3,"cache_read_tokens":2}}',
        '',
        'data: [DONE]',
        '',
      ].join('\n'),
    },
    {
      surface: 'responses' as const,
      body: [
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"responses stream"}',
        '',
        'event: response.completed',
        'data: {"type":"response.completed","response":{"status":"completed","output":[],"usage":' +
          '{"input_tokens":7,"output_tokens":3,"input_tokens_details":{"cached_tokens":2}}}}',
        '',
      ].join('\n'),
    },
    {
      surface: 'messages' as const,
      body: [
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"messages stream"}}',
        '',
        'event: message_delta',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":5,"output_tokens":3,' +
          '"cache_read_input_tokens":2,"cache_creation_input_tokens":0}}',
        '',
        'event: message_stop',
        'data: {"type":"message_stop"}',
        '',
      ].join('\n'),
    },
  ])('normalizes streamed $surface events', async ({ surface, body }) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(streamResponse([encoder.encode(body)])));
    const deltas: string[] = [];

    await expect(
      inferenceCompletion({
        surface,
        model: 'model-1',
        messages: [{ role: 'user', content: 'hi' }],
        maxTokens: 128,
        stream: true,
        onDelta: (content) => deltas.push(content),
      }),
    ).resolves.toMatchObject({
      content: `${surface === 'oai_compatible' ? 'canonical' : surface} stream`,
      usage: { inputTokens: 7, outputTokens: 3, cacheReadTokens: 2 },
      finishReason: 'stop',
    });
    expect(deltas).toEqual([`${surface === 'oai_compatible' ? 'canonical' : surface} stream`]);
  });
});
