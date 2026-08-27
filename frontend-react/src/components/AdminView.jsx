import React, { useState, useEffect } from 'react'
import { 
  RotateCcw, 
  ArrowLeft, 
  MessageSquare, 
  Database,
  RefreshCw,
  Clock,
  ExternalLink
} from 'lucide-react'

function AdminView({ navigate }) {
  const API_BASE = import.meta.env.VITE_API_URL || window.location.origin
  
  const [sessions, setSessions] = useState([])
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  // Fetch session list
  const loadSessions = async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true)
    try {
      const resp = await fetch(`${API_BASE}/admin/sessions`)
      if (resp.ok) {
        const data = await resp.json()
        setSessions(data || [])
      }
    } catch (e) {
      console.error("Error fetching admin sessions:", e)
    } finally {
      setRefreshing(false)
    }
  }

  // Load details of selected session
  const loadDetail = async (sessionId) => {
    setLoading(true)
    try {
      const resp = await fetch(`${API_BASE}/admin/sessions/${sessionId}`)
      if (resp.ok) {
        const data = await resp.json()
        setSessionDetail(data)
      }
    } catch (e) {
      console.error("Error loading session detail:", e)
    } finally {
      setLoading(false)
    }
  }

  // Reload session list and details on interval
  useEffect(() => {
    loadSessions()
    const timer = setInterval(() => {
      loadSessions()
    }, 5000)
    return () => clearInterval(timer)
  }, [])

  // Auto reload details if currently active session updates
  useEffect(() => {
    if (selectedSessionId) {
      const timer = setInterval(() => {
        loadDetail(selectedSessionId)
      }, 5000)
      return () => clearInterval(timer)
    }
  }, [selectedSessionId])

  // Select session handler
  const handleSelectSession = (sessionId) => {
    setSelectedSessionId(sessionId)
    loadDetail(sessionId)
  }

  // Reset session handler
  const handleResetSession = async (sessionId) => {
    if (window.confirm(`Are you sure you want to clear session ${sessionId}?`)) {
      try {
        await fetch(`${API_BASE}/reset/${sessionId}`, { method: 'POST' })
        if (selectedSessionId === sessionId) {
          setSessionDetail(null)
          setSelectedSessionId(null)
        }
        loadSessions()
      } catch (e) {
        console.error("Reset error:", e)
      }
    }
  }

  return (
    <div className="admin-layout">
      
      {/* ================= ADMIN SIDEBAR ================= */}
      <div className="admin-sidebar">
        <div className="admin-sidebar-header">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 }}>
              <Database size={16} />
              Conversations
            </h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button 
                className="btn-shiny" 
                style={{ padding: '4px 6px' }} 
                onClick={() => loadSessions(true)}
                disabled={refreshing}
              >
                <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
              </button>
              <button 
                className="btn-shiny" 
                style={{ padding: '4px 8px', fontSize: 11 }} 
                onClick={() => navigate('/')}
              >
                <ArrowLeft size={11} style={{ marginRight: 4 }} />
                Chat
              </button>
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            Monitoring {sessions.length} active sessions
          </div>
        </div>

        <div className="session-list">
          {sessions.length > 0 ? (
            sessions.map((s) => (
              <div 
                key={s.session_id} 
                className={`session-item ${selectedSessionId === s.session_id ? 'active' : ''}`}
                onClick={() => handleSelectSession(s.session_id)}
              >
                <div className="session-item-header">
                  <span className="session-dest">{s.destination || 'Destination unknown'}</span>
                  {s.stage && <span className="session-stage-badge">{s.stage}</span>}
                </div>
                <div className="session-preview">{s.last_message || '(no messages)'}</div>
                <div className="session-meta">
                  <span>{s.session_id}</span>
                  <span style={{ margin: '0 6px' }}>·</span>
                  <span>{s.message_count || 0} msgs</span>
                </div>
              </div>
            ))
          ) : (
            <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '40px 20px', fontSize: 13 }}>
              No active sessions found.
            </div>
          )}
        </div>
      </div>

      {/* ================= ADMIN DETAILS AREA ================= */}
      <div className="admin-detail-col">
        {selectedSessionId && sessionDetail ? (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 30 }}>
            
            {/* Detail Header */}
            <div className="admin-detail-header">
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>Session ID: {selectedSessionId}</h2>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 12, color: 'var(--text-dim)' }}>
                  {sessionDetail.model_provider && (
                    <span className="model-badge" style={{ fontSize: 10, background: 'rgba(255,255,255,0.05)', padding: '2px 6px' }}>
                      ENGINE: {sessionDetail.model_provider.toUpperCase()}
                    </span>
                  )}
                  <span>•</span>
                  <span>Conversational History monitor</span>
                </div>
              </div>
              
              <button className="btn-shiny" onClick={() => handleResetSession(selectedSessionId)}>
                <RotateCcw size={12} />
                Delete/Reset Session
              </button>
            </div>

            {/* Split layout: transcript and state grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 30, alignItems: 'start' }}>
              
              {/* Message Transcript */}
              <div>
                <h3 className="sidebar-section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <MessageSquare size={13} />
                  Conversation Transcript
                </h3>
                
                <div className="admin-transcript">
                  {sessionDetail.history && sessionDetail.history.length > 0 ? (
                    sessionDetail.history.filter(msg => typeof msg.content === 'string').map((msg, idx) => (
                      <div key={idx} className={`admin-msg-bubble ${msg.role === 'user' ? 'user' : 'assistant'}`}>
                        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 4, fontWeight: 500 }}>
                          {msg.role === 'user' ? 'GUEST' : 'MEHMAN.IO'}
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                          {msg.content}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: '20px 0' }}>
                      No messages recorded in this conversation.
                    </div>
                  )}
                </div>
              </div>

              {/* Booking state parameters */}
              <div>
                <h3 className="sidebar-section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Database size={13} />
                  Extracted Booking State
                </h3>

                <div className="state-grid-ui">
                  {[
                    { label: "Destination", val: sessionDetail.state.destination },
                    { label: "Check-in Date", val: sessionDetail.state.check_in },
                    { label: "Check-out Date", val: sessionDetail.state.check_out },
                    { label: "Guests Count", val: sessionDetail.state.num_guests },
                    { label: "Budget per night", val: sessionDetail.state.budget_per_night_inr ? `₹${sessionDetail.state.budget_per_night_inr}` : null },
                    { label: "Selected Property", val: sessionDetail.state.selected_property_id },
                    { label: "Selected Room", val: sessionDetail.state.selected_room_type },
                    { label: "Booking Stage", val: sessionDetail.state.stage },
                  ].map((item, idx) => (
                    <div key={idx} className={`state-card ${item.val ? 'filled' : 'empty'}`}>
                      <span className="state-card-label">{item.label}</span>
                      <span className="state-card-value">{item.val || '—'}</span>
                    </div>
                  ))}
                </div>
              </div>

            </div>

          </div>
        ) : (
          <div className="admin-empty-state">
            <Database size={40} style={{ marginBottom: 16, color: 'var(--text-dim)' }} />
            <p>Select a guest conversation from the sidebar to inspect parameters and history</p>
          </div>
        )}
      </div>

    </div>
  )
}

export default AdminView
