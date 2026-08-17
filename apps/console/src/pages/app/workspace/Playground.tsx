import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, Trash2, KeyRound, Loader2, User, Bot, AlertCircle, Zap, ChevronDown, Check, Search } from 'lucide-react';
import { useRequiredOrgId } from '@/lib/session';
import { useRequiredParam } from '@/lib/route';
import { useProviders } from '@/features/credentials/hooks';
import { useCreateInferenceKeyMutation } from '@/features/keys/hooks';
import { Button, Input, Badge, Card } from '@/components/ui/elements';
import { Textarea } from '@/components/ui/textarea';
import { PageShell } from '@/components/shared/page-shell';
import { LoadingState, ErrorState, EmptyState } from '@/components/shared/states';
import { ProviderIcon } from '@/components/ProviderIcon';
import type { ModelOut, ProviderOut } from '@workspace/api-client-react';
import { cn } from '@/lib/utils';

type Role = 'user' | 'assistant';
type ChatMessage = { role: Role; content: string };

function ModelPicker({
  groups,
  value,
  onChange,
}: {
  groups: { provider: ProviderOut; models: ModelOut[] }[];
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allModels = groups.flatMap((g) => g.models);
  const selectedModel = allModels.find((m) => m.name === value);
  const selectedProvider = selectedModel ? groups.find((g) => g.models.some((m) => m.id === selectedModel.id))?.provider : undefined;

  const q = query.toLowerCase();
  const filtered = groups
    .map((g) => ({
      ...g,
      models: g.models.filter((m) => !q || m.name.toLowerCase().includes(q) || g.provider.name.toLowerCase().includes(q)),
    }))
    .filter((g) => g.models.length > 0);

  useEffect(() => {
    if (!open) { setQuery(''); return; }
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-xs font-mono transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="flex min-w-0 items-center gap-2">
          {selectedProvider?.icon && <ProviderIcon markup={selectedProvider.icon} />}
          <span className="truncate">{selectedModel?.name ?? 'Select model'}</span>
        </span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-md border border-border bg-card shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search models..."
              className="flex-1 bg-transparent font-mono text-xs outline-none placeholder:text-muted-foreground"
            />
          </div>
          <ul role="listbox" className="permission-scrollbar max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 && (
              <li className="px-3 py-4 text-center font-mono text-xs text-muted-foreground">No models match</li>
            )}
            {filtered.map(({ provider, models }) => (
              <li key={provider.id}>
                <div className="flex items-center gap-2 px-3 py-1.5">
                  {provider.icon && <ProviderIcon markup={provider.icon} />}
                  <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{provider.name}</span>
                </div>
                <ul>
                  {models.map((model) => {
                    const active = model.name === value;
                    return (
                      <li key={model.id}>
                        <button
                          type="button"
                          role="option"
                          aria-selected={active}
                          onClick={() => { onChange(model.name); setOpen(false); }}
                          className={cn(
                            'flex w-full items-center justify-between px-3 py-1.5 font-mono text-xs transition-colors',
                            active ? 'bg-primary/10 text-primary' : 'hover:bg-accent hover:text-accent-foreground',
                          )}
                        >
                          <span className="truncate pl-4">{model.name}</span>
                          {active && <Check className="h-3 w-3 shrink-0" />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function groupByProvider(models: ModelOut[], providers: ProviderOut[]): { provider: ProviderOut; models: ModelOut[] }[] {
  const providerMap = new Map(providers.map((p) => [p.id, p]));
  const groups = new Map<string, ModelOut[]>();
  for (const model of models) {
    const list = groups.get(model.provider_id) ?? [];
    list.push(model);
    groups.set(model.provider_id, list);
  }
  return [...groups.entries()]
    .map(([providerId, groupModels]) => ({ provider: providerMap.get(providerId)!, models: groupModels }))
    .filter((g) => g.provider != null);
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border',
          isUser ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-muted text-muted-foreground',
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div
        className={cn(
          'max-w-[80%] rounded-xl px-4 py-2.5 text-sm',
          isUser ? 'rounded-tr-sm bg-primary text-primary-foreground' : 'rounded-tl-sm bg-card border border-border text-foreground',
        )}
      >
        <pre className="whitespace-pre-wrap font-sans">{message.content}</pre>
      </div>
    </div>
  );
}

function StreamingBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground">
        <Bot className="h-3.5 w-3.5" />
      </div>
      <div className="max-w-[80%] rounded-xl rounded-tl-sm border border-border bg-card px-4 py-2.5 text-sm text-foreground">
        <pre className="whitespace-pre-wrap font-sans">{content}</pre>
        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary" />
      </div>
    </div>
  );
}

export default function Playground() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();
  const taxonomyQuery = useProviders(orgId, workspaceRef);
  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);

  const models = taxonomyQuery.data?.models ?? [];
  const providers = taxonomyQuery.data?.providers ?? [];
  const groups = groupByProvider(models, providers);

  const [token, setToken] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState('1');
  const [maxTokens, setMaxTokens] = useState('');
  const [streamEnabled, setStreamEnabled] = useState(true);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (models.length > 0 && !selectedModel) {
      setSelectedModel(models[0].name);
    }
  }, [models, selectedModel]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const generateToken = useCallback(async () => {
    const minted = await createKey.mutateAsync({ orgId, workspaceRef, data: { label: 'playground' } });
    setToken(minted.token);
  }, [createKey, orgId, workspaceRef]);

  const send = useCallback(async () => {
    if (!input.trim() || !selectedModel || !token || sending) return;
    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    const history = [...messages, userMessage];
    setMessages(history);
    setInput('');
    setError(null);
    setSending(true);
    setStreamingContent('');

    const body = {
      model: selectedModel,
      messages: [
        ...(systemPrompt.trim() ? [{ role: 'system', content: systemPrompt.trim() }] : []),
        ...history.map((m) => ({ role: m.role, content: m.content })),
      ],
      temperature: parseFloat(temperature) || 1,
      ...(maxTokens ? { max_tokens: parseInt(maxTokens, 10) } : {}),
      stream: streamEnabled,
    };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch('/dp/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`${response.status}: ${text}`);
      }

      if (streamEnabled && response.body) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          for (const line of chunk.split('\n')) {
            const stripped = line.replace(/^data: /, '').trim();
            if (!stripped || stripped === '[DONE]') continue;
            try {
              const parsed = JSON.parse(stripped);
              const delta = parsed.choices?.[0]?.delta?.content;
              if (delta) {
                accumulated += delta;
                setStreamingContent(accumulated);
              }
            } catch {
              // partial chunk, ignore
            }
          }
        }
        setMessages((prev) => [...prev, { role: 'assistant', content: accumulated }]);
      } else {
        const data = await response.json();
        const content = data.choices?.[0]?.message?.content ?? '';
        setMessages((prev) => [...prev, { role: 'assistant', content }]);
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError((err as Error).message);
        setMessages((prev) => prev.slice(0, -1));
        setInput(userMessage.content);
      }
    } finally {
      setSending(false);
      setStreamingContent('');
      abortRef.current = null;
    }
  }, [input, selectedModel, token, sending, messages, systemPrompt, temperature, maxTokens, streamEnabled]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  if (taxonomyQuery.isLoading) return <LoadingState label="Loading workspace catalog..." />;
  if (taxonomyQuery.isError) return <ErrorState error={taxonomyQuery.error} resource="workspace catalog" onRetry={() => taxonomyQuery.refetch()} />;

  if (models.length === 0) {
    return (
      <PageShell>
        <EmptyState icon={Zap}>
          No models are available in this workspace. Add a provider credential and a model to the workspace catalog first.
        </EmptyState>
      </PageShell>
    );
  }

  const canSend = !!input.trim() && !!selectedModel && !!token && !sending;

  return (
    <PageShell className="h-[calc(100vh-2rem)] max-w-none flex flex-col gap-0 p-0 overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <aside className="permission-scrollbar w-72 shrink-0 overflow-y-auto border-r border-border bg-card/40 p-4 space-y-5">
          <div>
            <h1 className="font-mono text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">Playground</h1>
          </div>

          <div className="space-y-2">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Model</label>
            <ModelPicker groups={groups} value={selectedModel} onChange={setSelectedModel} />
          </div>

          <div className="space-y-2">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">System prompt</label>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful assistant."
              className="permission-scrollbar h-24 resize-none text-xs"
            />
          </div>

          <div className="space-y-2">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Temperature <span className="text-foreground">{temperature}</span>
            </label>
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />
            <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
              <span>0</span>
              <span>1</span>
              <span>2</span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Max tokens</label>
            <Input
              type="number"
              min={1}
              placeholder="Default"
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              className="h-8 text-xs font-mono"
            />
          </div>

          <div className="flex items-center justify-between">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Streaming</label>
            <button
              type="button"
              role="switch"
              aria-checked={streamEnabled}
              onClick={() => setStreamEnabled((v) => !v)}
              className={cn(
                'relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                streamEnabled ? 'bg-primary' : 'bg-muted',
              )}
            >
              <span
                className={cn(
                  'inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform',
                  streamEnabled ? 'translate-x-4' : 'translate-x-1',
                )}
              />
            </button>
          </div>

          <div className="space-y-2 border-t border-border pt-4">
            <label className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <KeyRound className="h-3 w-3" />
              Inference key
            </label>
            <Input
              type="password"
              placeholder="sk-inf-..."
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="h-8 font-mono text-xs"
            />
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              onClick={generateToken}
              disabled={createKey.isPending}
            >
              {createKey.isPending ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <KeyRound className="mr-1.5 h-3 w-3" />}
              Generate playground key
            </Button>
            {!token && (
              <p className="text-[10px] text-muted-foreground">Paste an existing key or generate one above.</p>
            )}
          </div>
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="permission-scrollbar flex-1 overflow-y-auto p-6 space-y-4">
            {messages.length === 0 && !sending && (
              <div className="flex h-full items-center justify-center">
                <div className="text-center space-y-2">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted">
                    <Zap className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <p className="font-mono text-sm text-muted-foreground">Send a message to start inferring</p>
                  {!token && (
                    <p className="text-xs text-destructive">Add an inference key in the sidebar first</p>
                  )}
                </div>
              </div>
            )}
            {messages.map((message, i) => (
              <MessageBubble key={i} message={message} />
            ))}
            {sending && streamingContent && <StreamingBubble content={streamingContent} />}
            {sending && !streamingContent && (
              <div className="flex gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground">
                  <Bot className="h-3.5 w-3.5" />
                </div>
                <div className="flex items-center gap-1.5 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-2.5">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
                </div>
              </div>
            )}
            {error && (
              <Card className="flex items-start gap-3 border-destructive/30 bg-destructive/5 p-3">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <div className="space-y-0.5">
                  <p className="text-xs font-medium text-destructive">Request failed</p>
                  <p className="font-mono text-[11px] text-destructive/80">{error}</p>
                </div>
              </Card>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-border bg-card/40 p-4">
            <div className="flex items-end gap-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder="Send a message... (Shift+Enter for newline)"
                className="permission-scrollbar max-h-40 min-h-[2.75rem] flex-1 resize-none text-sm"
                rows={1}
                disabled={sending}
              />
              <div className="flex shrink-0 gap-1.5">
                {messages.length > 0 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => { setMessages([]); setError(null); }}
                    disabled={sending}
                    title="Clear conversation"
                    aria-label="Clear conversation"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
                {sending ? (
                  <Button variant="outline" size="icon" onClick={stop} title="Stop generation" aria-label="Stop generation">
                    <span className="h-3 w-3 rounded-sm bg-foreground" />
                  </Button>
                ) : (
                  <Button size="icon" onClick={() => void send()} disabled={!canSend} title="Send message" aria-label="Send message">
                    <Send className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
            {selectedModel && (
              <div className="mt-2 flex items-center gap-1.5">
                <Badge variant="outline" className="font-mono text-[10px]">
                  {selectedModel}
                </Badge>
                {streamEnabled && <Badge variant="secondary" className="text-[10px]">STREAMING</Badge>}
              </div>
            )}
          </div>
        </main>
      </div>
    </PageShell>
  );
}
