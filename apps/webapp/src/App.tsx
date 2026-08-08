import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchMe, getCurrentOrg, listOrgs, logout, setCurrentOrg, type Me } from './api'
import { inputClass } from './ui'
import Login from './pages/Login'
import Events from './pages/Events'
import Orgs from './pages/Orgs'
import Keys from './pages/Keys'
import Providers from './pages/Providers'
import Models from './pages/Models'
import Bundles from './pages/Bundles'
import Instances from './pages/Instances'
import CliApprove from './pages/CliApprove'
import Onboarding from './pages/Onboarding'

const NAV = [
  { to: '/events', label: 'Events' },
  { to: '/orgs', label: 'Orgs' },
  { to: '/keys', label: 'Keys' },
  { to: '/providers', label: 'Providers' },
  { to: '/models', label: 'Models' },
  { to: '/bundles', label: 'Bundles' },
  { to: '/instances', label: 'Instances' },
]

function OrgSelect({ me }: { me: Me }) {
  const queryClient = useQueryClient()
  const { data: allOrgs } = useQuery({ queryKey: ['orgs'], queryFn: listOrgs, enabled: me.instance_admin })
  const options = me.instance_admin ? (allOrgs ?? []).map((o) => o.id) : me.orgs
  const [selected, setSelected] = useState(getCurrentOrg())
  const effective = selected && options.includes(selected) ? selected : (options[0] ?? null)

  useEffect(() => {
    if (effective !== getCurrentOrg()) {
      setCurrentOrg(effective)
      queryClient.invalidateQueries()
    }
  }, [effective, queryClient])

  if (options.length === 0) return null
  return (
    <div className="px-3 pb-2">
      <select
        className={`w-full ${inputClass}`}
        value={effective ?? ''}
        onChange={(e) => {
          setSelected(e.target.value)
          setCurrentOrg(e.target.value)
          queryClient.invalidateQueries()
        }}
      >
        {options.map((org) => (
          <option key={org} value={org}>
            {org}
          </option>
        ))}
      </select>
    </div>
  )
}

export default function App() {
  const queryClient = useQueryClient()
  const { data: me, isLoading } = useQuery({ queryKey: ['me'], queryFn: fetchMe })

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      setCurrentOrg(null)
      queryClient.clear()
    },
  })

  if (isLoading) return <div className="min-h-screen bg-slate-950" />
  if (!me) return <Login />
  if (window.location.pathname === '/cli') return <CliApprove />
  if (!me.instance_admin && me.orgs.length === 0) return <Onboarding />

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
        <OrgSelect me={me} />
        <div className="border-t border-slate-800 px-3 py-4">
          <p className="truncate px-3 text-xs text-slate-500" title={me.email}>
            {me.email}
          </p>
          <button
            type="button"
            className="mt-1 w-full rounded-md px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            onClick={() => signOut.mutate()}
          >
            Log out
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
          <Route path="/cli" element={<CliApprove />} />
        </Routes>
      </main>
    </div>
  )
}
