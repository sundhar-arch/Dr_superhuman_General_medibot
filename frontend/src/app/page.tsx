'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

const DEMO_USERS = [
  { username: 'dr.mehta',     password: 'password', role: 'doctor',            label: 'Dr. Mehta',    badge: 'bg-blue-900 text-blue-300' },
  { username: 'nurse.priya',  password: 'password', role: 'nurse',             label: 'Nurse Priya',  badge: 'bg-green-900 text-green-300' },
  { username: 'billing.ravi', password: 'password', role: 'billing_executive', label: 'Billing Ravi', badge: 'bg-orange-900 text-orange-300' },
  { username: 'tech.anand',   password: 'password', role: 'technician',        label: 'Tech Anand',   badge: 'bg-purple-900 text-purple-300' },
  { username: 'admin.sys',    password: 'password', role: 'admin',             label: 'Admin Sys',    badge: 'bg-red-900 text-red-300' },
]

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const router = useRouter()

  const doLogin = async (u: string, p: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      })
      if (!res.ok) {
        setError('Invalid credentials. Check username and password.')
        return
      }
      const data = await res.json()
      localStorage.setItem('token',    data.token)
      localStorage.setItem('role',     data.role)
      localStorage.setItem('username', data.username)
      router.push('/chat')
    } catch {
      setError('Cannot connect to backend (localhost:8000). Start the FastAPI server first.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md space-y-4">

        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">🏥</div>
          <h1 className="text-2xl font-bold text-white">Dr. Superhuman MediBot</h1>
          <p className="text-slate-400 mt-1 text-sm">MediAssist Health Network — Internal AI Assistant</p>
        </div>

        {/* Quick demo login */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <p className="text-xs uppercase tracking-wider font-semibold text-slate-400 mb-3">
            Quick Login — Demo Accounts
          </p>
          <div className="space-y-2">
            {DEMO_USERS.map(u => (
              <button
                key={u.username}
                onClick={() => doLogin(u.username, u.password)}
                disabled={loading}
                className="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors disabled:opacity-60 text-left"
              >
                <div>
                  <span className="text-white text-sm font-medium">{u.label}</span>
                  <span className="text-slate-400 text-xs ml-2">{u.username}</span>
                </div>
                <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${u.badge}`}>
                  {u.role.replace('_', ' ')}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Manual login */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <p className="text-xs uppercase tracking-wider font-semibold text-slate-400 mb-3">
            Manual Login
          </p>
          <div className="space-y-3">
            <input
              type="text"
              placeholder="Username"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full bg-slate-700 text-white placeholder-slate-400 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doLogin(username, password)}
              className="w-full bg-slate-700 text-white placeholder-slate-400 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
          <button
            onClick={() => doLogin(username, password)}
            disabled={loading || !username}
            className="mt-4 w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg py-3 text-sm font-semibold transition-colors"
          >
            {loading ? 'Logging in…' : 'Login'}
          </button>
        </div>

      </div>
    </div>
  )
}
