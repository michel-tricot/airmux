import { useEffect, useRef, useState } from 'react';
import { Send, Trash2, Loader2, User, Bot, AlertCircle, Zap, ShieldCheck, ChevronDown } from 'lucide-react';
import { useRequiredOrgId } from '@/lib/session';
import { useRequiredParam } from '@/lib/route';
import { useProviders } from '@/features/credentials/hooks';
import { Alert, AlertDescription, AlertTitle, Badge, Button, Input, Label, Modal, Switch } from '@/components/ui/elements';
import { Textarea } from '@/components/ui/textarea';
import { PageShell } from '@/components/shared/page-shell';
import { LoadingState, ErrorState, EmptyState } from '@/components/shared/states';
import { ProviderIcon } from '@/components/ProviderIcon';
import { cn } from '@/lib/utils';
import { inferenceCompletion, prepareInferenceRequest, type InferenceMessage } from '@/lib/inference';
import { useAuthorization } from '@/features/permissions/hooks';
import { catalogAccess } from '@/features/catalog/policy';
import { useEndPlaygroundSessionMutation, useEnsurePlaygroundSessionMutation } from '@/features/playground/hooks';
import { usePlaygroundState, type PlaygroundMessage, type PlaygroundRequest } from '@/features/playground/state';
import { ModelPicker } from '@/components/shared/model-picker';
import { useClipboardCopy } from '@/components/shared/use-clipboard-copy';
import { CopyButton, CopyFeedback } from '@/components/shared/copy-control';

function formatDuration(durationMs: number) {
  return durationMs < 1_000 ? `${Math.round(durationMs)} ms` : `${(durationMs / 1_000).toFixed(1)} s`;
}

function formatCost(costUsd: number) {
  return `$${costUsd.toFixed(costUsd < 0.01 ? 4 : 2)}`;
}

function curlFor(request: PlaygroundRequest) {
  const prepared = prepareInferenceRequest(request);
  const body = JSON.stringify(prepared.body, null, 2).replaceAll("'", "'\"'\"'");
  return [
    "curl '" + window.location.origin + prepared.path + "' \\",
    '  -H "Authorization: Bearer $AIRLLM_API_KEY" \\',
    "  -H 'Content-Type: application/json' \\",
    "  -H 'x-airllm-dialect: " + prepared.dialect + "' \\",
    "  --data-raw '" + body + "'",
  ].join('\n');
}

function CurlDialog({ open, onOpenChange, request }: { open: boolean; onOpenChange: (open: boolean) => void; request: PlaygroundRequest }) {
  const curl = curlFor(request);
  const curlText = useRef<HTMLPreElement>(null);
  const clipboard = useClipboardCopy(curl, curlText, request);

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Replicate request"
      description="Set AIRLLM_API_KEY to an inference key, then run this command from your terminal."
      contentClassName="sm:max-w-3xl"
    >
      <div className="min-w-0 space-y-3">
        <div className="min-w-0 max-w-full overflow-hidden rounded border border-border bg-background/60">
          <div className="flex justify-end border-b border-border p-2">
            <CopyButton {...clipboard} subject="cURL" />
          </div>
          <pre
            ref={curlText}
            tabIndex={-1}
            aria-label="cURL command"
            className={cn(
              'max-h-[60vh] min-w-0 max-w-full overflow-x-hidden overflow-y-auto p-4',
              'whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground',
            )}
          >
            {curl}
          </pre>
        </div>
        <CopyFeedback status={clipboard.status} errorMessage="Automatic copy was blocked. Press Command+C or Ctrl+C to copy the selected command." />
      </div>
    </Modal>
  );
}

function MessageBubble({ message }: { message: PlaygroundMessage }) {
  const isUser = message.role === 'user';
  const hasTextContent = !!message.content.trim();
  const stoppedAbnormally = message.finishReason !== undefined && message.finishReason !== 'stop';
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [curlOpen, setCurlOpen] = useState(false);
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
          {hasTextContent && <pre className="whitespace-pre-wrap font-sans">{message.content}</pre>}
          {stoppedAbnormally ? (
            <p role="status" className={cn('font-mono text-xs text-warning', hasTextContent && 'mt-2 border-t border-warning/20 pt-2')}>
              Response stopped: {message.finishReason}
            </p>
          ) : !hasTextContent ? (
            <span className="font-sans italic text-muted-foreground">No text content returned</span>
          ) : null}
        </div>
        {(message.interaction || message.request) && (
          <div className="space-y-1 pl-1 font-mono text-[10px] text-muted-foreground">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {message.interaction && (
                <>
                  <span>{message.interaction.model}</span>
                  <span>{message.interaction.inputTokens + message.interaction.outputTokens} total</span>
                  <span>Est. {formatCost(message.interaction.estimatedCostUsd)}</span>
                  <span>{formatDuration(message.interaction.durationMs)}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 gap-1 px-1.5 text-[10px]"
                    aria-expanded={detailsOpen}
                    aria-label={detailsOpen ? 'Hide response details' : 'Show response details'}
                    onClick={() => setDetailsOpen((open) => !open)}
                  >
                    {detailsOpen ? 'Hide details' : 'Show details'}
                    <ChevronDown className={cn('h-3 w-3 transition-transform', detailsOpen && 'rotate-180')} />
                  </Button>
                </>
              )}
              {message.request && (
                <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={() => setCurlOpen(true)}>
                  View cURL
                </Button>
              )}
            </div>
            {message.interaction && detailsOpen && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 border-l border-border pl-2">
                {message.interaction.provider && <span>{message.interaction.provider}</span>}
                <span>{message.interaction.inputTokens} input</span>
                <span>{message.interaction.outputTokens} output</span>
                <span>{message.interaction.cacheReadTokens} cached</span>
                {message.interaction.firstTokenMs !== undefined && <span>First token {formatDuration(message.interaction.firstTokenMs)}</span>}
                {message.finishReason && <span>{message.finishReason}</span>}
              </div>
            )}
          </div>
        )}
      </div>
      {message.request && <CurlDialog open={curlOpen} onOpenChange={setCurlOpen} request={message.request} />}
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
  const authorization = useAuthorization('workspace');
  const canReadCatalog = authorization.can(catalogAccess.workspace.read);
  const taxonomyQuery = useProviders(orgId, workspaceRef, { enabled: canReadCatalog });
  const ensureSession = useEnsurePlaygroundSessionMutation();
  const endSession = useEndPlaygroundSessionMutation();
  const [playground, setPlayground] = usePlaygroundState(`${orgId}:${workspaceRef}`);
  const { selectedModel, systemPrompt, temperature, maxTokens, streamEnabled, messages, input, sessionExpiresAt } = playground;
  const updatePlayground = (update: Partial<typeof playground>) => setPlayground((current) => ({ ...current, ...update }));

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

  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeModel = models.some((model) => model.name === selectedModel) ? selectedModel : (models[0]?.name ?? '');
  const activeModelDetails = models.find((model) => model.name === activeModel);
  const temperatureUnsupported = activeModelDetails?.parameter_support?.temperature === 'unsupported';

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

  const send = async () => {
    if (!input.trim() || !activeModel || sending) return;
    const userMessage: PlaygroundMessage = { role: 'user', content: input.trim() };
    const history = [...messages, userMessage];
    updatePlayground({ input: '' });
    composerRef.current?.focus();
    setError(null);
    setSending(true);
    setStreamingContent('');

    const controller = new AbortController();
    abortRef.current = controller;
    let partial = '';
    let requestStarted = false;

    try {
      const playgroundSession = await ensureSession.mutateAsync({ orgId, workspaceRef });
      if (abortRef.current !== controller) return;
      updatePlayground({ messages: history, sessionExpiresAt: playgroundSession.expires_at });
      requestStarted = true;
      const requestMessages: InferenceMessage[] = [
        ...(systemPrompt.trim() ? [{ role: 'system' as const, content: systemPrompt.trim() }] : []),
        ...history.map(({ role, content }) => ({ role, content })),
      ];
      const request: PlaygroundRequest = {
        model: activeModel,
        messages: requestMessages,
        temperature: temperatureUnsupported ? undefined : Number(temperature),
        maxTokens: maxTokens ? Number.parseInt(maxTokens, 10) : undefined,
        stream: streamEnabled,
      };
      const result = await inferenceCompletion({
        ...request,
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
      setPlayground((current) => ({
        ...current,
        messages: [
          ...current.messages,
          {
            role: 'assistant',
            content: result.content,
            finishReason: result.finishReason,
            request,
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
                }
              : undefined,
          },
        ],
      }));
    } catch (err) {
      if (abortRef.current !== controller) return;
      if ((err as Error).name === 'AbortError') {
        if (partial) setPlayground((current) => ({ ...current, messages: [...current.messages, { role: 'assistant', content: partial }] }));
      } else {
        setError((err as Error).message);
        setPlayground((current) => ({
          ...current,
          messages: requestStarted ? current.messages.slice(0, -1) : current.messages,
          input: current.input || userMessage.content,
        }));
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

  const endPlaygroundSession = async () => {
    await endSession.mutateAsync({ orgId, workspaceRef });
    updatePlayground({ sessionExpiresAt: null });
  };

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

  const canSend = !!input.trim() && !!activeModel && !sending;
  const hasConversationContent = messages.length > 0 || sending || error !== null;

  return (
    <PageShell className="h-[calc(100vh-2rem)] max-w-none flex flex-col gap-0 p-0 overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-72 shrink-0 overflow-y-auto border-r border-border bg-card/40 p-4 space-y-5">
          <div>
            <h1 className="font-mono text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3">Playground</h1>
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-model">Model</Label>
            <ModelPicker
              id="playground-model"
              aria-label="Model"
              className="h-8 text-xs"
              value={activeModel}
              onValueChange={(selectedModel) => updatePlayground({ selectedModel })}
              onSelectionComplete={() => composerRef.current?.focus()}
              options={modelOptions}
              placeholder="Select model"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-system-prompt">System prompt</Label>
            <Textarea
              id="playground-system-prompt"
              value={systemPrompt}
              onChange={(event) => updatePlayground({ systemPrompt: event.target.value })}
              placeholder="You are a helpful assistant."
              className="h-24 resize-none text-xs"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="playground-temperature">
              Temperature{' '}
              {temperatureUnsupported ? (
                <span className="font-normal text-muted-foreground">Not supported by this model</span>
              ) : (
                <span className="text-foreground">{temperature}</span>
              )}
            </Label>
            <input
              id="playground-temperature"
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={temperature}
              disabled={temperatureUnsupported}
              onChange={(event) => updatePlayground({ temperature: event.target.value })}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary disabled:cursor-not-allowed disabled:opacity-50"
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
              stepperLabel="Max tokens"
              onChange={(event) => updatePlayground({ maxTokens: event.target.value })}
              className="h-8 text-xs font-mono"
            />
          </div>

          <div className="flex items-center justify-between">
            <Label htmlFor="playground-streaming">Streaming</Label>
            <Switch
              id="playground-streaming"
              aria-label="Streaming"
              checked={streamEnabled}
              onCheckedChange={(streamEnabled) => updatePlayground({ streamEnabled })}
            />
          </div>

          <div className="space-y-2 border-t border-border pt-4">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                <ShieldCheck className="h-3 w-3" />
                Session
              </span>
              <Badge variant={sessionExpiresAt ? 'secondary' : 'outline'} className="text-[10px]">
                {sessionExpiresAt ? 'READY' : 'ON DEMAND'}
              </Badge>
            </div>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              {sessionExpiresAt
                ? `Active until ${new Date(sessionExpiresAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}. It stays available across pages.`
                : 'A private one-hour session starts automatically when you send a message.'}
            </p>
            {sessionExpiresAt && (
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs"
                onClick={() => void endPlaygroundSession()}
                disabled={sending || endSession.isPending}
              >
                {endSession.isPending && <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />}
                End session
              </Button>
            )}
          </div>
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {messages.length === 0 && !sending && (
              <div className="flex h-full items-center justify-center">
                <div className="text-center space-y-2">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted">
                    <Zap className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <p className="font-mono text-sm text-muted-foreground">Send a message to start inferring</p>
                  <p className="text-xs text-muted-foreground">Your playground session is prepared automatically.</p>
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
              <Alert variant="destructive" className="items-center border-destructive/30 bg-destructive/5 [&>svg]:mt-0">
                <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
                <AlertTitle className="mb-0 shrink-0">Request failed</AlertTitle>
                <AlertDescription className="font-mono text-[11px]">{error}</AlertDescription>
              </Alert>
            )}
            {hasConversationContent && <div ref={bottomRef} data-playground-scroll-anchor />}
          </div>

          <div className="border-t border-border bg-card/40 p-4">
            <div className="flex items-end gap-2">
              <Textarea
                ref={composerRef}
                value={input}
                onChange={(event) => updatePlayground({ input: event.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder="Send a message... (Shift+Enter for newline)"
                className="max-h-40 min-h-[2.75rem] flex-1 resize-none py-2.5 text-sm leading-5"
                rows={1}
              />
              <div className="flex shrink-0 gap-1.5">
                {messages.length > 0 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      updatePlayground({ messages: [] });
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
