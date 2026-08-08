import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, login, signup, type Me } from '../api'
import { Button, inputClass } from '../ui'

function errorMessage(error: unknown, mode: 'login' | 'signup'): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'wrong email or password'
    if (error.status === 409) return 'an account with this email already exists'
    if (error.status === 422) return 'password must be at least 8 characters'
  }
  return mode === 'login' ? 'login failed' : 'signup failed'
}

export default function Login() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')

  const submit = useMutation({
    mutationFn: () => (mode === 'login' ? login({ email, password }) : signup({ email, name, password })),
    onSuccess: (me: Me) => queryClient.setQueryData(['me'], me),
  })

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <form
        className="w-96 space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-8"
        onSubmit={(e) => {
          e.preventDefault()
          if (email.trim() && password) submit.mutate()
        }}
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-100">airllm console</h1>
          <p className="mt-1 text-sm text-slate-500">{mode === 'login' ? 'Log in to your account' : 'Create an account'}</p>
        </div>
        <input
          className={`w-full ${inputClass}`}
          type="email"
          placeholder="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
        {mode === 'signup' && (
          <input className={`w-full ${inputClass}`} type="text" placeholder="name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
        )}
        <input
          className={`w-full ${inputClass}`}
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {submit.error != null && <p className="text-sm text-red-400">{errorMessage(submit.error, mode)}</p>}
        <Button type="submit" disabled={submit.isPending}>
          {mode === 'login' ? 'Log in' : 'Sign up'}
        </Button>
        <button
          type="button"
          className="block text-sm text-slate-500 hover:text-slate-300"
          onClick={() => {
            setMode(mode === 'login' ? 'signup' : 'login')
            submit.reset()
          }}
        >
          {mode === 'login' ? 'No account? Sign up' : 'Have an account? Log in'}
        </button>
      </form>
    </div>
  )
}
