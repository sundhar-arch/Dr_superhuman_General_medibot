'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'

// ── Types ──────────────────────────────────────────────────────────────────
type Source = {
  source_document: string
  section_title:   string
  collection:      string
}

type Message = {
  id:             string
  role:           'user' | 'bot'
  content:        string
  retrieval_type?: string
  sources?:       Source[]
  isBlocked?:     boolean
}

// ── Constants ──────────────────────────────────────────────────────────────
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const ROLE_BADGE: Record<string, string> = {
  doctor:            'bg-blue-900   text-blue-300',
  nurse:             'bg-green-900  text-green-300',
  billing_executive: 'bg-orange-900 text-orange-300',
  technician:        'bg-purple-900 text-purple-300',
  admin:             'bg-red-900    text-red-300',
}

const COLLECTION_COLOR: Record<string, string> = {
  clinical: 'text-blue-400',
  nursing:  'text-green-400',
  billing:  'text-orange-400',
  equipment:'text-purple-400',
  general:  'text-slate-400',
}

const RETRIEVAL_BADGE: Record<string, string> = {
  hybrid_rag:          'bg-emerald-900 text-emerald-300',
  sql_rag:             'bg-violet-900  text-violet-300',
  hybrid_rag_blocked:  'bg-red-900     text-red-300',
  sql_rag_blocked:     'bg-red-900     text-red-300',
}

const RETRIEVAL_LABEL: Record<string, string> = {
  hybrid_rag:         'Hybrid RAG',
  sql_rag:            'SQL RAG',
  hybrid_rag_blocked: 'Access Denied',
  sql_rag_blocked:    'Access Denied',
}

// ── Component ──────────────────────────────────────────────────────────────
export default function ChatPage() {
  const [messages,    setMessages]    = useState<Message[]>([])
  const [input,       setInput]       = useState('')
  const [loading,     setLoading]     = useState(false)
  const [collections, setCollections] = useState<string[]>([])
  const [username,    setUsername]    = useState('')
  const [role,        setRole]        = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const router    = useRouter()

  const logout = useCallback(() => {
    localStorage.clear()
    router.push('/')
  }, [router])

  useEffect(() => {
    const token        = localStorage.getItem('token')
    const storedRole   = localStorage.getItem('role')    || ''
    const storedUser   = localStorage.getItem('username') || ''
    if (!token) { router.push('/'); return }

    setRole(storedRole)
    setUsername(storedUser)

    // C9 fix: authenticated request; role derived from token server-side
    fetch(`${API_BASE}/collections`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(r => r.json())
      .then(d => setCollections(d.collections ?? []))
      .catch(() => {})

    setMessages([{
      id:      'welcome',
      role:    'bot',
      content: `Welcome, ${storedUser}! I'm MediBot — your intelligent clinical assistant for MediAssist Health Network. Ask me anything within your permitted collections.`,
    }])
  }, [router])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async () => {
    const question = input.trim()
    if (!question || loading) return
    setInput('')

    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      // C1 fix: role verified from Bearer token server-side, not from request body
      const res  = await fetch(`${API_BASE}/chat`, {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token') ?? ''}`,
        },
        body:    JSON.stringify({ question }),
      })
      const data = await res.json()
      const botMsg: Message = {
        id:             (Date.now() + 1).toString(),
        role:           'bot',
        content:        data.answer,
        retrieval_type: data.retrieval_type,
        sources:        data.sources,
        isBlocked:      (data.retrieval_type ?? '').includes('blocked'),
      }
      setMessages(prev => [...prev, botMsg])
    } catch {
      setMessages(prev => [...prev, {
        id:      (Date.now() + 1).toString(),
        role:    'bot',
        content: 'Error: Could not reach the backend server at localhost:8000.',
      }])
    } finally {
      setLoading(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex bg-slate-900 overflow-hidden">

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="w-56 shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col p-4">
        <div className="mb-6">
          <div className="text-lg font-bold text-white">🏥 MediBot</div>
          <div className="text-xs text-slate-500 mt-0.5">MediAssist Health Network</div>
        </div>

        <div className="mb-5">
          <p className="text-xs uppercase tracking-wider font-semibold text-slate-500 mb-2">Signed in as</p>
          <p className="text-sm font-medium text-white truncate">{username}</p>
          <span className={`inline-block mt-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${ROLE_BADGE[role] ?? 'bg-slate-700 text-slate-300'}`}>
            {role.replace('_', ' ')}
          </span>
        </div>

        <div className="flex-1 min-h-0">
          <p className="text-xs uppercase tracking-wider font-semibold text-slate-500 mb-2">My Collections</p>
          <ul className="space-y-1.5">
            {collections.map(col => (
              <li key={col} className="flex items-center gap-2 text-sm">
                <span className={`w-1.5 h-1.5 rounded-full ${COLLECTION_COLOR[col]?.replace('text-', 'bg-') ?? 'bg-slate-400'}`} />
                <span className={COLLECTION_COLOR[col] ?? 'text-slate-300'}>{col}</span>
              </li>
            ))}
          </ul>
        </div>

        <button
          onClick={logout}
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors text-left mt-4"
        >
          ← Logout
        </button>
      </aside>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <div className="shrink-0 border-b border-slate-700 px-6 py-4">
          <h1 className="text-white font-semibold text-sm">Dr. Superhuman General MediBot</h1>
          <p className="text-slate-500 text-xs mt-0.5">Advanced RAG · Hybrid Search · RBAC · SQL RAG</p>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {messages.map(msg => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>

              {msg.role === 'user' ? (
                <div className="max-w-lg bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed">
                  {msg.content}
                </div>
              ) : (
                <div className="max-w-2xl space-y-2">
                  <div className={`rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed ${
                    msg.isBlocked
                      ? 'bg-red-950 border border-red-800 text-red-200'
                      : 'bg-slate-800 text-slate-100'
                  }`}>
                    <p className="whitespace-pre-wrap">{msg.content}</p>

                    {/* Retrieval type badge */}
                    {msg.retrieval_type && (
                      <div className="mt-2.5">
                        <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                          RETRIEVAL_BADGE[msg.retrieval_type] ?? 'bg-slate-700 text-slate-300'
                        }`}>
                          {RETRIEVAL_LABEL[msg.retrieval_type] ?? msg.retrieval_type}
                        </span>
                      </div>
                    )}

                    {/* Source citations */}
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-slate-700">
                        <p className="text-slate-400 text-xs font-semibold mb-2">Sources used</p>
                        <div className="space-y-1.5">
                          {msg.sources.map((src, i) => (
                            <div key={i} className="text-xs bg-slate-700/60 rounded-lg px-3 py-2 flex items-start gap-2">
                              <span className="mt-0.5">📄</span>
                              <div>
                                <span className="text-slate-200 font-medium">{src.source_document}</span>
                                {src.section_title && src.section_title !== 'General' && (
                                  <span className="text-slate-400"> · {src.section_title}</span>
                                )}
                                <span className={`ml-1.5 font-medium ${COLLECTION_COLOR[src.collection] ?? 'text-slate-400'}`}>
                                  [{src.collection}]
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-800 rounded-2xl rounded-tl-sm px-4 py-3 flex gap-1.5 items-center">
                {[0, 150, 300].map(delay => (
                  <span
                    key={delay}
                    className="w-2 h-2 bg-slate-400 rounded-full animate-bounce"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="shrink-0 border-t border-slate-700 px-6 py-4">
          <div className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
              placeholder="Ask MediBot anything…"
              className="flex-1 bg-slate-800 border border-slate-700 text-white placeholder-slate-500 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl px-5 py-3 text-sm font-semibold transition-colors"
            >
              Send
            </button>
          </div>
          <p className="text-slate-600 text-xs mt-2 text-center">
            RBAC enforced at vector retrieval layer · Powered by Groq + Qdrant
          </p>
        </div>
      </main>
    </div>
  )
}
