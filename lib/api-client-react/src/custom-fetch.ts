export type CustomFetchOptions = RequestInit & {
  responseType?: 'json' | 'text' | 'blob' | 'auto';
};

export type ErrorType<T = unknown> = ApiError<T>;

export type BodyType<T> = T;

export type AuthTokenGetter = () => Promise<string | null> | string | null;

export type DefaultHeadersGetter = () => Record<string, string | null>;

const NO_BODY_STATUS = new Set([204, 205, 304]);
const DEFAULT_JSON_ACCEPT = 'application/json, application/problem+json';

let _baseUrl: string | null = null;
let _authTokenGetter: AuthTokenGetter | null = null;
let _defaultHeadersGetter: DefaultHeadersGetter | null = null;

export function setBaseUrl(url: string | null): void {
  _baseUrl = url ? url.replace(/\/+$/, '') : null;
}

export function setAuthTokenGetter(getter: AuthTokenGetter | null): void {
  _authTokenGetter = getter;
}

export function setDefaultHeaders(getter: DefaultHeadersGetter | null): void {
  _defaultHeadersGetter = getter;
}

function isRequest(input: RequestInfo | URL): input is Request {
  return typeof Request !== 'undefined' && input instanceof Request;
}

function resolveMethod(input: RequestInfo | URL, explicitMethod?: string): string {
  if (explicitMethod) return explicitMethod.toUpperCase();
  if (isRequest(input)) return input.method.toUpperCase();
  return 'GET';
}

function isUrl(input: RequestInfo | URL): input is URL {
  return Object.prototype.toString.call(input) === '[object URL]';
}

function applyBaseUrl(input: RequestInfo | URL): RequestInfo | URL {
  if (!_baseUrl) return input;
  const url = resolveUrl(input);
  if (!url.startsWith('/')) return input;

  const absolute = `${_baseUrl}${url}`;
  if (typeof input === 'string') return absolute;
  if (isUrl(input)) return new URL(absolute);
  return new Request(absolute, input as Request);
}

function resolveUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (isUrl(input)) return input.toString();
  return input.url;
}

function mergeHeaders(...sources: Array<HeadersInit | undefined>): Headers {
  const headers = new Headers();

  for (const source of sources) {
    if (!source) continue;
    new Headers(source).forEach((value, key) => {
      headers.set(key, value);
    });
  }

  return headers;
}

function getMediaType(headers: Headers): string | null {
  const value = headers.get('content-type');
  return value ? value.split(';', 1)[0].trim().toLowerCase() : null;
}

function isJsonMediaType(mediaType: string | null): boolean {
  return mediaType === 'application/json' || Boolean(mediaType?.endsWith('+json'));
}

function isTextMediaType(mediaType: string | null): boolean {
  return Boolean(
    mediaType &&
    (mediaType.startsWith('text/') ||
      mediaType === 'application/xml' ||
      mediaType === 'text/xml' ||
      mediaType.endsWith('+xml') ||
      mediaType === 'application/x-www-form-urlencoded'),
  );
}

function hasNoBody(response: Response, method: string): boolean {
  if (method === 'HEAD') return true;
  if (NO_BODY_STATUS.has(response.status)) return true;
  if (response.headers.get('content-length') === '0') return true;
  if (response.body === null) return true;
  return false;
}

function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

function looksLikeJson(text: string): boolean {
  const trimmed = text.trimStart();
  return trimmed.startsWith('{') || trimmed.startsWith('[');
}

function getStringField(value: unknown, key: string): string | undefined {
  if (!value || typeof value !== 'object') return undefined;

  const candidate = (value as Record<string, unknown>)[key];
  if (typeof candidate !== 'string') return undefined;

  const trimmed = candidate.trim();
  return trimmed === '' ? undefined : trimmed;
}

function truncate(text: string, maxLength = 300): string {
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function buildErrorMessage(response: Response, data: unknown): string {
  const prefix = `HTTP ${response.status} ${response.statusText}`;

  if (typeof data === 'string') {
    const text = data.trim();
    return text ? `${prefix}: ${truncate(text)}` : prefix;
  }

  const title = getStringField(data, 'title');
  const detail = getStringField(data, 'detail');
  const message = getStringField(data, 'message') ?? getStringField(data, 'error_description') ?? getStringField(data, 'error');

  if (title && detail) return `${prefix}: ${title} - ${detail}`;
  if (detail) return `${prefix}: ${detail}`;
  if (message) return `${prefix}: ${message}`;
  if (title) return `${prefix}: ${title}`;

  return prefix;
}

export class ApiError<T = unknown> extends Error {
  readonly name = 'ApiError';
  readonly status: number;
  readonly statusText: string;
  readonly data: T | null;
  readonly headers: Headers;
  readonly response: Response;
  readonly method: string;
  readonly url: string;

  constructor(response: Response, data: T | null, requestInfo: { method: string; url: string }) {
    super(buildErrorMessage(response, data));
    Object.setPrototypeOf(this, new.target.prototype);

    this.status = response.status;
    this.statusText = response.statusText;
    this.data = data;
    this.headers = response.headers;
    this.response = response;
    this.method = requestInfo.method;
    this.url = response.url || requestInfo.url;
  }
}

export class ResponseParseError extends Error {
  readonly name = 'ResponseParseError';
  readonly status: number;
  readonly statusText: string;
  readonly headers: Headers;
  readonly response: Response;
  readonly method: string;
  readonly url: string;
  readonly rawBody: string;
  readonly cause: unknown;

  constructor(response: Response, rawBody: string, cause: unknown, requestInfo: { method: string; url: string }) {
    super(
      `Failed to parse response from ${requestInfo.method} ${response.url || requestInfo.url} ` +
        `(${response.status} ${response.statusText}) as JSON`,
    );
    Object.setPrototypeOf(this, new.target.prototype);

    this.status = response.status;
    this.statusText = response.statusText;
    this.headers = response.headers;
    this.response = response;
    this.method = requestInfo.method;
    this.url = response.url || requestInfo.url;
    this.rawBody = rawBody;
    this.cause = cause;
  }
}

async function parseJsonBody(response: Response, requestInfo: { method: string; url: string }): Promise<unknown> {
  const raw = await response.text();
  const normalized = stripBom(raw);

  if (normalized.trim() === '') {
    return null;
  }

  try {
    return JSON.parse(normalized);
  } catch (cause) {
    throw new ResponseParseError(response, raw, cause, requestInfo);
  }
}

async function parseErrorBody(response: Response, method: string): Promise<unknown> {
  if (hasNoBody(response, method)) {
    return null;
  }

  const mediaType = getMediaType(response.headers);

  if (mediaType && !isJsonMediaType(mediaType) && !isTextMediaType(mediaType)) {
    return typeof response.blob === 'function' ? response.blob() : response.text();
  }

  const raw = await response.text();
  const normalized = stripBom(raw);
  const trimmed = normalized.trim();

  if (trimmed === '') {
    return null;
  }

  if (isJsonMediaType(mediaType) || looksLikeJson(normalized)) {
    try {
      return JSON.parse(normalized);
    } catch {
      return raw;
    }
  }

  return raw;
}

function unwrapEnvelope(body: unknown): unknown {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return body;

  const keys = Object.keys(body as Record<string, unknown>);
  return keys.length === 1 && keys[0] === 'data' ? (body as { data: unknown }).data : body;
}

function inferResponseType(response: Response): 'json' | 'text' | 'blob' {
  const mediaType = getMediaType(response.headers);

  if (isJsonMediaType(mediaType)) return 'json';
  if (isTextMediaType(mediaType) || mediaType == null) return 'text';
  return 'blob';
}

async function parseSuccessBody(
  response: Response,
  responseType: 'json' | 'text' | 'blob' | 'auto',
  requestInfo: { method: string; url: string },
): Promise<unknown> {
  if (hasNoBody(response, requestInfo.method)) {
    return null;
  }

  const effectiveType = responseType === 'auto' ? inferResponseType(response) : responseType;

  switch (effectiveType) {
    case 'json':
      return unwrapEnvelope(await parseJsonBody(response, requestInfo));

    case 'text': {
      const text = await response.text();
      return text === '' ? null : text;
    }

    case 'blob':
      if (typeof response.blob !== 'function') {
        throw new TypeError('Blob responses are not supported in this runtime. ' + 'Use responseType "json" or "text" instead.');
      }
      return response.blob();
  }
}

export async function customFetch<T = unknown>(input: RequestInfo | URL, options: CustomFetchOptions = {}): Promise<T> {
  input = applyBaseUrl(input);
  const { responseType = 'auto', headers: headersInit, ...init } = options;

  const method = resolveMethod(input, init.method);

  if (init.body != null && (method === 'GET' || method === 'HEAD')) {
    throw new TypeError(`customFetch: ${method} requests cannot have a body.`);
  }

  const headers = mergeHeaders(isRequest(input) ? input.headers : undefined, headersInit);

  if (typeof init.body === 'string' && !headers.has('content-type') && looksLikeJson(init.body)) {
    headers.set('content-type', 'application/json');
  }

  if (responseType === 'json' && !headers.has('accept')) {
    headers.set('accept', DEFAULT_JSON_ACCEPT);
  }

  if (_authTokenGetter && !headers.has('authorization')) {
    const token = await _authTokenGetter();
    if (token) {
      headers.set('authorization', `Bearer ${token}`);
    }
  }

  for (const [key, value] of Object.entries(_defaultHeadersGetter?.() ?? {})) {
    if (value !== null && !headers.has(key)) headers.set(key, value);
  }

  const requestInfo = { method, url: resolveUrl(input) };

  const response = await fetch(input, { ...init, method, headers });

  if (!response.ok) {
    const errorData = await parseErrorBody(response, method);
    throw new ApiError(response, errorData, requestInfo);
  }

  return (await parseSuccessBody(response, responseType, requestInfo)) as T;
}
