import { useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { clearToken, getToken, setToken } from './api'
import { inputClass, Button } from './ui'
import Events from './pages/Events'
import Orgs from './pages/Orgs'
import Keys from './pages/Keys'
import Providers from './pages/Providers'
import Models from './pages/Models'
import Bundles from './pages/Bundles'
import Instances from './pages/Instances'

const NAV = [
  { to: '/events', label: 'Events' },
  { to: '/orgs', label: 'Orgs' },
  { to: '/keys', label: 'Keys' },
  { to: '/providers', label: 'Providers' },
  { to: '/models', label: 'Models' },
  { to: '/bundles', label: 'Bundles' },
  { to: '/instances', label: 'Instances' },
]

function TokenGate({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState('')
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <form
        className="w-96 space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-8"
        onSubmit={(e) => {
          e.preventDefault()
          if (value.trim()) onSubmit(value.trim())
        }}
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-100">airllm console</h1>
          <p className="mt-1 text-sm text-slate-500">Enter a control plane management token</p>
        </div>
        <input
          className={`w-full ${inputClass}`}
          type="password"
          placeholder="management token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoFocus
        />
        <Button type="submit">Connect</Button>
      </form>
    </div>
  )
}

export default function App() {
  const [token, setTokenState] = useState(getToken())
  const queryClient = useQueryClient()

  if (!token) {
    return (
      <TokenGate
        onSubmit={(value) => {
          setToken(value)
          setTokenState(value)
        }}
      />
    )
  }

  return (
    <div className="flex min-h-screen bg-slate-950">
      <aside className="flex w-52 flex-col border-r border-slate-800 bg-slate-900">
        <div className="px-5 py-6">
          <span className="text-base font-semibold text-slate-100">airllm</span>
          <span className="ml-2 text-xs text-slate-500">console</span>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm ${
                  isActive ? 'bg-indigo-950 text-indigo-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-4">
          <button
            type="button"
            className="w-full rounded-md px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            onClick={() => {
              clearToken()
              setTokenState(null)
              queryClient.clear()
            }}
          >
            Reset token
          </button>
        </div>
      </aside>
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/events" replace />} />
          <Route path="/events" element={<Events />} />
          <Route path="/orgs" element={<Orgs />} />
          <Route path="/keys" element={<Keys />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/models" element={<Models />} />
          <Route path="/bundles" element={<Bundles />} />
          <Route path="/instances" element={<Instances />} />
        </Routes>
      </main>
    </div>
  )
}
