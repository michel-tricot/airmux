import { useEffect, useRef, useState } from 'react';
import { Send, Trash2, KeyRound, Loader2, User, Bot, AlertCircle, Zap } from 'lucide-react';
import { useRequiredOrgId } from '@/lib/session';
import { useRequiredParam } from '@/lib/route';
import { useProviders } from '@/features/credentials/hooks';
import { useCreateInferenceKeyMutation } from '@/features/keys/hooks';
import { Alert, AlertDescription, AlertTitle, Badge, Button, Input, Label, SearchableDropdown, Switch } from '@/components/ui/elements';
import { Textarea } from '@/components/ui/textarea';
import { PageShell } from '@/components/shared/page-shell';
import { LoadingState, ErrorState, EmptyState } from '@/components/shared/states';
import { ProviderIcon } from '@/components/ProviderIcon';
import { cn } from '@/lib/utils';
import { chatCompletion, type InferenceMessage } from '@/lib/inference';
import { hasPermission, useEffectivePermissions } from '@/features/permissions/hooks';

type Role = 'user' | 'assistant';
type Interaction = {
  model: string;
  provider: string | undefined;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  estimatedCostUsd: number;
  durationMs: number;
  firstTokenMs: number | undefined;
  finishReason: string | undefined;
};
type ChatMessage = { role: Role; content: string; interaction?: Interaction };

function formatDuration(durationMs: number) {
  return durationMs < 1_000 ? `${Math.round(durationMs)} ms` : `${(durationMs / 1_000).toFixed(1)} s`;
}

function formatCost(costUsd: number) {
  return `$${costUsd.toFixed(costUsd < 0.01 ? 4 : 2)}`;
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
      <div className="max-w-[80%] space-y-2">
        <div
          className={cn(
            'rounded-xl px-4 py-2.5 text-sm',
            isUser ? 'rounded-tr-sm bg-primary text-primary-foreground' : 'rounded-tl-sm border border-border bg-card text-foreground',
          )}
        >
          <pre className="whitespace-pre-wrap font-sans">{message.content}</pre>
        </div>
        {message.interaction && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 pl-1 font-mono text-[10px] text-muted-foreground">
            <span>{message.interaction.model}</span>
            {message.interaction.provider && <span>{message.interaction.provider}</span>}
            <span>{message.interaction.inputTokens} input</span>
            <span>{message.interaction.outputTokens} output</span>
            <span>{message.interaction.inputTokens + message.interaction.outputTokens} total</span>
            {message.interaction.cacheReadTokens > 0 && <span>{message.interaction.cacheReadTokens} cached</span>}
            <span>Est. {formatCost(message.interaction.estimatedCostUsd)}</span>
            <span>{formatDuration(message.interaction.durationMs)}</span>
            {message.interaction.firstTokenMs !== undefined && <span>First token {formatDuration(message.interaction.firstTokenMs)}</span>}
            {message.interaction.finishReason && <span>{message.interaction.finishReason}</span>}
          </div>
        )}
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

export default function ScopedPlayground() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  return <Playground key={`${orgId}:${workspaceRef}`} orgId={orgId} workspaceRef={workspaceRef} />;
}

function Playground({ orgId, workspaceRef }: { orgId: string; workspaceRef: string }) {
  const permissionsQuery = useEffectivePermissions({ orgId, workspaceRef });
  const permissions = permissionsQuery.data?.permissions;
  const canReadCatalog = hasPermission(permissions, 'catalog.read');
  const canManageKeys = hasPermission(permissions, 'inference-keys.manage');
  const taxonomyQuery = useProviders(orgId, workspaceRef, canReadCatalog);
  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);

  const models = taxonomyQuery.data?.models ?? [];
  const providers = taxonomyQuery.data?.providers ?? [];
  const providerById = new Map(providers.map((provider) => [provider.id, provider]));
  const modelOptions = models.map((model) => {
    const provider = providerById.get(model.provider_id);
    return {
      value: model.name,
      searchText: `${model.name} ${provider?.name ?? ''}`,
      label: (
        <span className="flex min-w-0 items-center gap-2">
          {provider?.icon && <ProviderIcon markup={provider.icon} />}
          <span className="truncate">{model.name}</span>
          {provider && <span className="ml-auto text-[10px] text-muted-foreground">{provider.name}</span>}
        </span>
      ),
    };
  });

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
  const activeModel = models.some((model) => model.name === selectedModel) ? selectedModel : (models[0]?.name ?? '');
  const activeModelDetails = models.find((model) => model.name === activeModel);

  useEffect(() => {
    return () => {
      const controller = abortRef.current;
      abortRef.current = null;
      controller?.abort();
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const generateToken = async () => {
    const minted = await createKey.mutateAsync({ orgId, workspaceRef, data: { label: 'playground' } });
    setToken(minted.token);
  };

  const send = async () => {
    if (!input.trim() || !activeModel || !token || sending) return;
    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    const history = [...messages, userMessage];
    setMessages(history);
    setInput('');
    setError(null);
    setSending(true);
    setStreamingContent('');

    const controller = new AbortController();
    abortRef.current = controller;
    let partial = '';

    try {
      const requestMessages: InferenceMessage[] = [
        ...(systemPrompt.trim() ? [{ role: 'system' as const, content: systemPrompt.trim() }] : []),
        ...history,
      ];
      const result = await chatCompletion({
        token,
        model: activeModel,
        messages: requestMessages,
        temperature: Number(temperature),
        maxTokens: maxTokens ? Number.parseInt(maxTokens, 10) : undefined,
        stream: streamEnabled,
        signal: controller.signal,
        onDelta: (content) => {
          partial = content;
          setStreamingContent(content);
        },
      });
      if (abortRef.current !== controller) return;
      const usage = result.usage;
      const freshInputTokens = Math.max(0, (usage?.inputTokens ?? 0) - (usage?.cacheReadTokens ?? 0));
      const estimatedCostUsd = activeModelDetails
        ? (freshInputTokens * activeModelDetails.input_price_per_mtok +
            (usage?.cacheReadTokens ?? 0) * activeModelDetails.cache_read_price_per_mtok +
            (usage?.outputTokens ?? 0) * activeModelDetails.output_price_per_mtok) /
          1_000_000
        : 0;
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: result.content,
          interaction: usage
            ? {
                model: activeModel,
                provider: activeModelDetails ? providerById.get(activeModelDetails.provider_id)?.name : undefined,
                inputTokens: usage.inputTokens,
                outputTokens: usage.outputTokens,
                cacheReadTokens: usage.cacheReadTokens,
                estimatedCostUsd,
                durationMs: result.durationMs,
                firstTokenMs: result.firstTokenMs,
                finishReason: result.finishReason,
              }
            : undefined,
        },
      ]);
    } catch (err) {
      if (abortRef.current !== controller) return;
      if ((err as Error).name === 'AbortError') {
        if (partial) setMessages((current) => [...current, { role: 'assistant', content: partial }]);
      } else {
        setError((err as Error).message);
        setMessages((current) => current.slice(0, -1));
        setInput(userMessage.content);
      }
    } finally {
      if (abortRef.current === controller) {
        setSending(false);
        setStreamingContent('');
        abortRef.current = null;
      }
    }
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  if (permissionsQuery.isLoading) return <LoadingState label="Loading workspace permissions..." />;
  if (permissionsQuery.isError)
    return <ErrorState error={permissionsQuery.error} resource="workspace permissions" onRetry={() => permissionsQuery.refetch()} />;
  if (!canReadCatalog) return <ErrorState message="You do not have access to the catalog in this workspace." />;
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

  const canSend = !!input.trim() && !!activeModel && !!token && !sending;

  return (
    <PageShell className="h-[calc(100vh-2rem)] max-w-none flex flex-col gap-0 p-0 overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <aside className="permission-scrollbar w-72 shrink-0 overflow-y-auto border-r border-border bg-card/40 p-4 space-y-5">
          <div>
            <h1 className="font-mono text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">Playground</h1>
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-model">Model</Label>
            <SearchableDropdown
              id="playground-model"
              aria-label="Model"
              className="h-8 text-xs"
              value={activeModel}
              onValueChange={setSelectedModel}
              options={modelOptions}
              placeholder="Select model"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-system-prompt">System prompt</Label>
            <Textarea
              id="playground-system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful assistant."
              className="permission-scrollbar h-24 resize-none text-xs"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-temperature">
              Temperature <span className="text-foreground">{temperature}</span>
            </Label>
            <input
              id="playground-temperature"
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
            <Label htmlFor="playground-max-tokens">Max tokens</Label>
            <Input
              id="playground-max-tokens"
              type="number"
              min={1}
              placeholder="Default"
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              className="h-8 text-xs font-mono"
            />
          </div>

          <div className="flex items-center justify-between">
            <Label htmlFor="playground-streaming">Streaming</Label>
            <Switch id="playground-streaming" aria-label="Streaming" checked={streamEnabled} onCheckedChange={setStreamEnabled} />
          </div>

          <div className="space-y-2 border-t border-border pt-4">
            <Label htmlFor="playground-key" className="flex items-center gap-1.5">
              <KeyRound className="h-3 w-3" />
              Inference key
            </Label>
            <Input
              id="playground-key"
              type="password"
              placeholder="sk-inf-..."
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="h-8 font-mono text-xs"
            />
            {canManageKeys && (
              <Button variant="outline" size="sm" className="w-full text-xs" onClick={generateToken} disabled={createKey.isPending}>
                {createKey.isPending ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <KeyRound className="mr-1.5 h-3 w-3" />}
                Generate playground key
              </Button>
            )}
            {!token && <p className="text-[10px] text-muted-foreground">Paste an existing key or generate one above.</p>}
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
                  {!token && <p className="text-xs text-destructive">Add an inference key in the sidebar first</p>}
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
              <Alert variant="destructive" className="border-destructive/30 bg-destructive/5">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <AlertTitle>Request failed</AlertTitle>
                <AlertDescription className="font-mono text-[11px]">{error}</AlertDescription>
              </Alert>
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
                    onClick={() => {
                      setMessages([]);
                      setError(null);
                    }}
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
            {activeModel && (
              <div className="mt-2 flex items-center gap-1.5">
                <Badge variant="outline" className="font-mono text-[10px]">
                  {activeModel}
                </Badge>
                {streamEnabled && (
                  <Badge variant="secondary" className="text-[10px]">
                    STREAMING
                  </Badge>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </PageShell>
  );
}
