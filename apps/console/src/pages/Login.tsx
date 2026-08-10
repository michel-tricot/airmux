import { useState } from 'react';
import * as z from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { useLogin, useSignup, useClaim, getMeQueryKey, type MeOut } from '@workspace/api-client-react';
import { Card, Button, Input } from '@/components/ui/elements';
import { TerminalSquare } from 'lucide-react';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  name: z.string(),
  password: z.string().min(1, 'Password is required'),
});

const signupSchema = loginSchema.extend({
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type Credentials = z.infer<typeof loginSchema>;

export default function Login() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  // An unclaimed deployment hands the first account its instance, which is worth saying out loud.
  const { data: claim } = useClaim();

  const form = useForm<Credentials>({
    resolver: zodResolver(mode === 'login' ? loginSchema : signupSchema),
    defaultValues: { email: '', name: '', password: '' },
  });

  // The response is the same MeOut the session reads, so seeding the cache signs the user in
  // without a second round trip. Auth failures render inline, so the global toast is silenced.
  const onSuccess = (me: MeOut) => queryClient.setQueryData(getMeQueryKey(), me);
  const login = useLogin({ mutation: { onSuccess, meta: { silentError: true } } });
  const signup = useSignup({ mutation: { onSuccess, meta: { silentError: true } } });
  const pending = login.isPending || signup.isPending;
  const error = mode === 'login' ? login.error : signup.error;

  const submit = form.handleSubmit(values => {
    if (mode === 'login') login.mutate({ data: { email: values.email, password: values.password } });
    else signup.mutate({ data: { email: values.email, name: values.name, password: values.password } });
  });

  const switchMode = () => {
    setMode(m => (m === 'login' ? 'signup' : 'login'));
    form.clearErrors();
    login.reset();
    signup.reset();
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4 shadow-[0_0_20px_rgba(97,94,255,0.4)]">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-xl font-mono font-bold tracking-widest uppercase">
            {mode === 'login' ? 'Sign in' : 'Create an account'}
          </h1>
          <p className="text-muted-foreground text-sm mt-2 text-center max-w-sm">
            {mode === 'login'
              ? 'Sign in with your account credentials.'
              : claim?.claimed === false
                ? 'The first account becomes the administrator.'
                : 'You can join or create an organization after signing up.'}
          </p>
        </div>

        <Form {...form}>
          <form onSubmit={submit} className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" autoComplete="username" placeholder="you@example.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {mode === 'signup' && (
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="Jane Doe" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Password</FormLabel>
                  <FormControl>
                    <Input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {error && (
              <div className="p-3 rounded-md bg-destructive/10 border border-destructive/20 text-destructive text-sm">
                {mode === 'login' ? 'Sign in failed. Check your email and password.' : 'We couldn’t create your account. Please check your details and try again.'}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={pending}>
              {pending ? (mode === 'login' ? 'Signing in...' : 'Creating account...') : mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>
        </Form>

        <Button variant="ghost" className="w-full mt-4 text-muted-foreground hover:text-foreground" onClick={switchMode}>
          {mode === 'login' ? 'No account? Sign up' : 'Already have an account? Sign in'}
        </Button>
      </Card>
    </div>
  );
}
