import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLogin, useSignup, useClaim, getMeQueryKey, type MeOut } from '@workspace/api-client-react';
import { Card, Button, Input, Label } from '@/components/ui/elements';
import { TerminalSquare } from 'lucide-react';

export default function Login() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  // An unclaimed deployment hands the first account its instance, which is worth saying out loud.
  const { data: claim } = useClaim();
  const [form, setForm] = useState({ email: '', name: '', password: '' });

  // The response is the same MeOut the session reads, so seeding the cache signs the user in
  // without a second round trip.
  const onSuccess = (me: MeOut) => queryClient.setQueryData(getMeQueryKey(), me);
  const login = useLogin({ mutation: { onSuccess } });
  const signup = useSignup({ mutation: { onSuccess } });
  const pending = login.isPending || signup.isPending;
  const error = login.error ?? signup.error;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'login') login.mutate({ data: { email: form.email, password: form.password } });
    else signup.mutate({ data: { email: form.email, name: form.name, password: form.password } });
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">
            {mode === 'login' ? 'Sign in to Gateway' : 'Create an account'}
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            {mode === 'login'
              ? 'Use your control plane credentials.'
              : claim?.claimed === false
                ? 'This deployment has no account yet: the first one becomes its instance admin.'
                : 'A new account starts with no orgs and no admin rights.'}
          </p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required autoComplete="username" value={form.email}
              onChange={e => setForm(p => ({ ...p, email: e.target.value }))} placeholder="you@example.com" />
          </div>

          {mode === 'signup' && (
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} placeholder="Jane Doe" />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" required minLength={mode === 'signup' ? 8 : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={form.password}
              onChange={e => setForm(p => ({ ...p, password: e.target.value }))} />
          </div>

          {error && (
            <div className="p-3 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm">
              {mode === 'login' ? 'Sign in failed. Check your email and password.' : error.message}
            </div>
          )}

          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? 'Working...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
        </form>

        <Button variant="ghost" className="w-full mt-4 text-muted-foreground hover:text-foreground"
          onClick={() => setMode(m => (m === 'login' ? 'signup' : 'login'))}>
          {mode === 'login' ? 'No account? Sign up' : 'Already have an account? Sign in'}
        </Button>
      </Card>
    </div>
  );
}
