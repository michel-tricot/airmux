import type { ReactNode } from 'react'
import { ApiError } from './api'

export function Page({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
        {actions}
      </div>
      {children}
    </div>
  )
}

export function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            {headers.map((h) => (
              <th key={h} className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 text-slate-300">{children}</tbody>
      </table>
    </div>
  )
}

export function Td({ children, mono = false }: { children: ReactNode; mono?: boolean }) {
  return <td className={`px-4 py-2.5 ${mono ? 'font-mono text-xs' : ''}`}>{children}</td>
}

export function Badge({ tone, children }: { tone: 'ok' | 'warn' | 'err'; children: ReactNode }) {
  const tones = {
    ok: 'bg-emerald-950 text-emerald-400 ring-emerald-800',
    warn: 'bg-amber-950 text-amber-400 ring-amber-800',
    err: 'bg-red-950 text-red-400 ring-red-800',
  }
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs ring-1 ${tones[tone]}`}>{children}</span>
}

export function Button({ children, onClick, disabled = false, danger = false, type = 'button' }: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  danger?: boolean
  type?: 'button' | 'submit'
}) {
  const color = danger
    ? 'bg-red-900/50 text-red-300 hover:bg-red-900 ring-red-800'
    : 'bg-indigo-600 text-white hover:bg-indigo-500 ring-indigo-500'
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-sm font-medium ring-1 transition disabled:opacity-40 ${color}`}
    >
      {children}
    </button>
  )
}

export const inputClass =
  'rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none'

export function QueryStatus({ isLoading, error, empty }: { isLoading: boolean; error: unknown; empty: boolean }) {
  if (isLoading) return <p className="text-sm text-slate-500">Loading...</p>
  if (error) {
    const message = error instanceof ApiError ? error.message : 'request failed, is the control plane running?'
    return <p className="text-sm text-red-400">{message}</p>
  }
  if (empty) return <p className="text-sm text-slate-500">Nothing here yet</p>
  return null
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(6)}`
}
