import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, createPersonalOrg, logout, setCurrentOrg } from '../api'
import { Button, inputClass } from '../ui'

export default function Onboarding() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: () => createPersonalOrg({ name }),
    onSuccess: (org) => {
      setCurrentOrg(org.id)
      queryClient.invalidateQueries()
    },
  })

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      setCurrentOrg(null)
      queryClient.clear()
    },
  })

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <form
        className="w-96 space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-8"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Welcome to airllm</h1>
          <p className="mt-1 text-sm text-slate-500">Create your organization to get started, or ask your admin to add you to one</p>
        </div>
        <input
          className={`w-full ${inputClass}`}
          placeholder="organization name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        {create.error != null && (
          <p className="text-sm text-red-400">
            {create.error instanceof ApiError && create.error.status === 409 ? 'you already have a personal organization' : 'could not create the organization'}
          </p>
        )}
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          Create organization
        </Button>
        <button type="button" className="block text-sm text-slate-500 hover:text-slate-300" onClick={() => signOut.mutate()}>
          Log out
        </button>
      </form>
    </div>
  )
}
