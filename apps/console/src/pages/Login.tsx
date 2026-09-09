import { useState } from 'react';
import * as z from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { useLogin, useSignup, useClaim, getMeQueryKey, type MeOut } from '@workspace/api-client-react';
import { Alert, AlertDescription, AlertTitle, Card, Button, Input } from '@/components/ui/elements';
import { TerminalSquare } from 'lucide-react';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  name: z.string(),
  password: z.string().min(1, 'Password is required'),
});

const signupSchema = loginSchema.extend({
  name: z.string().min(1, 'Name is required'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type Credentials = z.infer<typeof loginSchema>;
type LoginMode = 'login' | 'signup';
type InitialLoginMode = LoginMode | 'choice';

export default function Login({
  initialEmail = '',
  initialMode = 'login',
  emailReadOnly = false,
  invitationToken,
  heading,
  description,
}: {
  initialEmail?: string;
  initialMode?: InitialLoginMode;
  emailReadOnly?: boolean;
  invitationToken?: string;
  heading?: string;
  description?: string;
} = {}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<InitialLoginMode>(initialMode);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const { data: claim } = useClaim();
  const unclaimedInstance = claim?.claimed === false;
  const activeMode = unclaimedInstance ? 'signup' : mode;

  const form = useForm<Credentials>({
    resolver: zodResolver(activeMode === 'signup' ? signupSchema : loginSchema),
    defaultValues: { email: initialEmail, name: '', password: '' },
  });

  const onSuccess = (me: MeOut) => queryClient.setQueryData(getMeQueryKey(), me);
  const login = useLogin({
    mutation: {
      onSuccess,
    },
  });
  const signup = useSignup({
    mutation: {
      onSuccess,
      meta: { silentError: true },
    },
  });
  const pending = login.isPending || signup.isPending;
  const publicSignupClosed = claim?.claimed === true && claim.public_signup === false;
  const signupAvailable = invitationToken !== undefined || claim?.public_signup === true;

  const submit = form.handleSubmit(async (values) => {
    setSubmissionError(null);
    form.clearErrors('password');
    try {
      if (activeMode === 'login') await login.mutateAsync({ data: { email: values.email, password: values.password } });
      else
        await signup.mutateAsync({
          data: { email: values.email, name: values.name, password: values.password, invitation_token: invitationToken },
        });
    } catch {
      if (activeMode === 'login') {
        setSubmissionError('Sign in failed. Check your email and password.');
        form.setError('password', { type: 'server', message: 'Incorrect email or password' });
      } else {
        setSubmissionError('We couldn’t create your account. Please check your details and try again.');
      }
    }
  });

  const switchMode = () => {
    setMode((m) => (m === 'login' ? 'signup' : 'login'));
    form.clearErrors();
    setSubmissionError(null);
    login.reset();
    signup.reset();
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4 shadow-md">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-xl font-mono font-bold tracking-widest uppercase">
            {heading ??
              (unclaimedInstance
                ? 'Create administrator account'
                : activeMode === 'choice'
                  ? 'Continue'
                  : activeMode === 'login'
                    ? 'Sign in'
                    : 'Create an account')}
          </h1>
          <p className="text-muted-foreground text-sm mt-2 text-center max-w-sm">
            {description ??
              (unclaimedInstance
                ? 'Create the first account to claim this instance.'
                : activeMode === 'choice'
                  ? 'Choose whether to create an account or sign in.'
                  : activeMode === 'login'
                    ? 'Sign in with your account credentials.'
                    : 'You can join or create an organization after signing up.')}
          </p>
        </div>

        {unclaimedInstance && (
          <Alert className="mb-4">
            <div>
              <AlertTitle>Claiming this instance</AlertTitle>
              <AlertDescription>This first account will have instance administrator access.</AlertDescription>
            </div>
          </Alert>
        )}

        <Form {...form}>
          <form onSubmit={activeMode === 'choice' ? (event) => event.preventDefault() : submit} noValidate className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" autoComplete="username" placeholder="you@example.com" readOnly={emailReadOnly} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {activeMode === 'choice' ? (
              <div className="space-y-3 pt-2">
                <Button className="w-full" onClick={() => setMode('signup')}>
                  Create account
                </Button>
                <Button variant="outline" className="w-full" onClick={() => setMode('login')}>
                  Sign in to existing account
                </Button>
              </div>
            ) : (
              <>
                {activeMode === 'signup' && (
                  <>
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
                  </>
                )}

                <FormField
                  control={form.control}
                  name="password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Password</FormLabel>
                      <FormControl>
                        <Input type="password" autoComplete={activeMode === 'login' ? 'current-password' : 'new-password'} {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {submissionError && (
                  <Alert variant="destructive">
                    <div>
                      <AlertTitle>{activeMode === 'login' ? 'Couldn’t sign in' : 'Couldn’t create account'}</AlertTitle>
                      <AlertDescription>{submissionError}</AlertDescription>
                    </div>
                  </Alert>
                )}

                <Button type="submit" className="w-full" disabled={pending}>
                  {pending
                    ? activeMode === 'login'
                      ? 'Signing in...'
                      : 'Creating account...'
                    : activeMode === 'login'
                      ? 'Sign in'
                      : 'Create account'}
                </Button>
              </>
            )}
          </form>
        </Form>

        {!unclaimedInstance && mode !== 'choice' && signupAvailable && (
          <Button variant="ghost" className="w-full mt-4 text-muted-foreground hover:text-foreground" onClick={switchMode}>
            {mode === 'login' ? 'No account? Sign up' : 'Already have an account? Sign in'}
          </Button>
        )}

        {mode === 'login' && publicSignupClosed && invitationToken === undefined && (
          <Alert className="mt-4">
            <div>
              <AlertTitle>Account creation is restricted</AlertTitle>
              <AlertDescription>Contact an instance administrator for an invitation.</AlertDescription>
            </div>
          </Alert>
        )}
      </Card>
    </div>
  );
}
