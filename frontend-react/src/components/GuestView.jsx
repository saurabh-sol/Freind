import React, { useState, useEffect, useRef } from 'react'
import { 
  Send, 
  RotateCcw, 
  Code, 
  ChevronLeft, 
  ChevronRight, 
  User, 
  Sparkles, 
  Terminal, 
  Database, 
  ExternalLink,
  Cpu,
  Layers,
  Activity
} from 'lucide-react'

// Render Markdown-like formatting (bold, tables, lists, linebreaks)
const renderMarkdown = (text) => {
  if (!text) return '';
  
  // Basic HTML escaping
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
    
  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  
  // Parse tables
  const lines = html.split('\n');
  let inTable = false;
  let tableRows = [];
  let processedLines = [];
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      if (!inTable) {
        inTable = true;
        tableRows = [];
      }
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      tableRows.push(cells);
    } else {
      if (inTable) {
        inTable = false;
        let tableHtml = '<table>';
        const hasSeparator = tableRows.length > 1 && tableRows[1].every(cell => cell.startsWith('-') || cell.startsWith(':'));
        
        tableRows.forEach((row, rowIndex) => {
          if (rowIndex === 1 && hasSeparator) return;
          const cellTag = (rowIndex === 0) ? 'th' : 'td';
          tableHtml += '<tr>';
          row.forEach(cell => {
            tableHtml += `<${cellTag}>${cell}</${cellTag}>`;
          });
          tableHtml += '</tr>';
        });
        tableHtml += '</table>';
        processedLines.push(tableHtml);
        tableRows = [];
      }
      processedLines.push(line);
    }
  }
  
  if (inTable && tableRows.length > 0) {
    let tableHtml = '<table>';
    tableRows.forEach((row, rowIndex) => {
      const cellTag = (rowIndex === 0) ? 'th' : 'td';
      tableHtml += '<tr>';
      row.forEach(cell => {
        tableHtml += `<${cellTag}>${cell}</${cellTag}>`;
      });
      tableHtml += '</tr>';
    });
    tableHtml += '</table>';
    processedLines.push(tableHtml);
  }
  
  // Parse bullet lists
  let inList = false;
  let listHtml = '';
  const finalLines = [];
  
  processedLines.forEach(line => {
    const match = line.match(/^[\-\*]\s+(.*)/);
    if (match) {
      if (!inList) {
        inList = true;
        listHtml = '<ul>';
      }
      listHtml += `<li>${match[1]}</li>`;
    } else {
      if (inList) {
        inList = false;
        listHtml += '</ul>';
        finalLines.push(listHtml);
        listHtml = '';
      }
      finalLines.push(line);
    }
  });
  
  if (inList) {
    listHtml += '</ul>';
    finalLines.push(listHtml);
  }
  
  return finalLines.join('\n').replace(/\n/g, '<br/>');
};

// JSON Syntax Highlighting
const syntaxHighlight = (jsonObj) => {
  if (!jsonObj) return '';
  let json = JSON.stringify(jsonObj, null, 2);
  json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, function (match) {
    let cls = 'number';
    if (/^"/.test(match)) {
      if (/:$/.test(match)) {
        cls = 'key';
      } else {
        cls = 'string';
      }
    } else if (/true|false/.test(match)) {
      cls = 'boolean';
    } else if (/null/.test(match)) {
      cls = 'null';
    }
    return '<span class="json-' + cls + '">' + match + '</span>';
  });
};

function GuestView({ navigate }) {
  // Session Init
  const [sessionId] = useState(() => {
    let id = localStorage.getItem('mira_session_id');
    if (!id) {
      id = 'session-' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem('mira_session_id', id);
    }
    return id;
  });

  const API_BASE = import.meta.env.VITE_API_URL || window.location.origin;

  // UI state
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(false);
  const [bookingState, setBookingState] = useState({});
  const [traceLog, setTraceLog] = useState([]);
  const [activeModel, setActiveModel] = useState('');
  const [activeProvider, setActiveProvider] = useState('Groq');
  
  // JSON viewer log history (captures the raw responses of each LLM turn)
  const [jsonHistory, setJsonHistory] = useState([]);
  const [selectedJsonIndex, setSelectedJsonIndex] = useState(-1);

  // Sidebars collapse state
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  // Suggested prompts
  const suggestions = [
    { title: "Trip to Goa", desc: "Goa this weekend for 3 people, budget 10k/night", text: "Looking for a stay in Goa this weekend for 3 guests, budget up to ₹10,000 per night." },
    { title: "Luxury in Udaipur", desc: "Udaipur palace stay with lake view", text: "I'd like to book a luxury lake view hotel in Udaipur." },
    { title: "Mumbai business trip", desc: "Single room near Bandra under 5k", text: "Looking for a single room near Bandra, Mumbai for tomorrow. Budget is ₹5,000." },
    { title: "Family resort in Manali", desc: "Kid-friendly with mountain views", text: "Need a kid-friendly resort in Manali for 4 people with great mountain views." }
  ];

  // Auto scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Textarea auto resize
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [inputText]);

  // Load health check and initial session history
  useEffect(() => {
    const fetchSession = async () => {
      try {
        // Fetch Provider
        const healthResp = await fetch(`${API_BASE}/health`);
        if (healthResp.ok) {
          const healthData = await healthResp.json();
          const prov = healthData.provider || 'groq';
          setActiveProvider(prov);
          const modelMap = {
            'groq': 'llama-3.3-70b-versatile',
            'openai': 'gpt-4o',
            'gemini': 'gemini-3.6-flash',
            'claude': 'claude-haiku-4-5'
          };
          setActiveModel(modelMap[prov.toLowerCase()] || prov);
        }

        // Fetch Session History
        const resp = await fetch(`${API_BASE}/admin/sessions/${sessionId}`);
        if (resp.ok) {
          const data = await resp.json();
          setBookingState(data.state || {});
          
          if (data.history && data.history.length > 0) {
            const parsedMsgs = data.history
              .filter(msg => typeof msg.content === 'string')
              .map(msg => ({
                role: msg.role === 'user' ? 'user' : 'assistant',
                text: msg.content
              }));
            setMessages(parsedMsgs);
          } else {
            // First time greeting
            setMessages([{
              role: 'assistant',
              text: "Hi! I'm Mera. Tell me what kind of stay you're looking for — destination, dates, number of guests, or anything else on your mind!"
            }]);
          }
        }
      } catch (e) {
        console.error("Error loading session:", e);
        // Fallback greeting on error
        setMessages([{
          role: 'assistant',
          text: "Hi! I'm Mira. Tell me what kind of stay you're looking for — destination, dates, number of guests, or anything else on your mind!"
        }]);
      }
    };
    fetchSession();
  }, [sessionId]);

  // Send message
  const handleSendMessage = async (textToSend) => {
    const text = (textToSend || inputText).trim();
    if (!text || loading) return;
    
    setInputText('');
    setLoading(true);
    setMessages(prev => [...prev, { role: 'user', text }]);

    try {
      const resp = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      
      if (!resp.ok) throw new Error("Server responded with error status");
      
      const data = await resp.json();
      
      // Update states
      setMessages(prev => [...prev, { role: 'assistant', text: data.reply || '(no reply)' }]);
      setBookingState(data.state || {});
      setTraceLog(data.trace || []);
      
      if (data.model_provider) {
        setActiveProvider(data.model_provider);
        const modelMap = {
          'groq': 'llama-3.3-70b-versatile',
          'openai': 'gpt-4o',
          'gemini': 'gemini-3.6-flash',
          'claude': 'claude-haiku-4-5'
        };
        setActiveModel(modelMap[data.model_provider.toLowerCase()] || data.model_provider);
      }

      // Add to JSON log history
      setJsonHistory(prev => {
        const nextHist = [...prev, {
          timestamp: new Date().toLocaleTimeString(),
          userMessage: text,
          model: activeModel,
          payload: data
        }];
        setSelectedJsonIndex(nextHist.length - 1);
        return nextHist;
      });

    } catch (e) {
      console.error(e);
      setMessages(prev => [...prev, { role: 'assistant', text: 'Error connecting to backend: ' + e.message }]);
    } finally {
      setLoading(false);
    }
  };

  // Reset conversation
  const handleResetSession = async () => {
    if (window.confirm("Are you sure you want to reset this booking session?")) {
      try {
        setLoading(true);
        await fetch(`${API_BASE}/reset/${sessionId}`, { method: 'POST' });
        setMessages([{
          role: 'assistant',
          text: "Hi! I'm Mera. Tell me what kind of stay you're looking for — destination, dates, number of guests, or anything else on your mind!"
        }]);
        setBookingState({});
        setTraceLog([]);
        setJsonHistory([]);
        setSelectedJsonIndex(-1);
      } catch (e) {
        console.error("Reset error:", e);
      } finally {
        setLoading(false);
      }
    }
  };

  // Build grid wrapper classes
  let containerClasses = "app-container";
  if (leftCollapsed && rightCollapsed) containerClasses += " both-collapsed";
  else if (leftCollapsed) containerClasses += " left-collapsed";
  else if (rightCollapsed) containerClasses += " right-collapsed";

  return (
    <div className={containerClasses}>
      
      {/* ================= LEFT SIDEBAR (JSON VIEWER) ================= */}
      {leftCollapsed ? (
        <div className="collapse-handle" onClick={() => setLeftCollapsed(false)}>
          <div className="vertical-text">JSON TRACE</div>
          <ChevronRight size={14} style={{ marginTop: 'auto', marginBottom: 20 }} />
        </div>
      ) : (
        <div className="panel shiny-texture">
          <div className="left-sidebar-header">
            <span className="sidebar-title">
              <Code size={16} />
              JSON Responses
            </span>
            <button className="btn-shiny" style={{ padding: '4px 6px' }} onClick={() => setLeftCollapsed(true)}>
              <ChevronLeft size={16} />
            </button>
          </div>


          {/* Turn selector tabs */}
          {jsonHistory.length > 0 && (
            <div className="json-nav-tabs">
              {jsonHistory.map((item, idx) => (
                <button
                  key={idx}
                  className={`json-tab ${selectedJsonIndex === idx ? 'active' : ''}`}
                  onClick={() => setSelectedJsonIndex(idx)}
                >
                  Turn {idx + 1}
                </button>
              ))}
            </div>
          )}

          <div className="json-container">
            {selectedJsonIndex >= 0 && jsonHistory[selectedJsonIndex] ? (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8, fontFamily: 'var(--font-sans)' }}>
                  Captured at {jsonHistory[selectedJsonIndex].timestamp}
                </div>
                <div 
                  className="json-wrapper"
                  dangerouslySetInnerHTML={{ __html: syntaxHighlight(jsonHistory[selectedJsonIndex].payload) }}
                />
              </div>
            ) : (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '40px 10px', fontFamily: 'var(--font-sans)', fontSize: 13 }}>
                No model calls captured yet. Send a message to inspect the raw LLM transaction.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ================= CENTER CHAT COLUMN ================= */}
      <div className="chat-area">
        <div className="chat-header">
          <div className="header-brand">
            <div className="brand-logo">M</div>
            <div>
              <div className="brand-text">Mera</div>
              <div className="brand-sub">Hotel Assistant</div>
            </div>
          </div>
          
          <div className="header-actions">
            <button className="btn-shiny" onClick={handleResetSession}>
              <RotateCcw size={13} />
              Reset
            </button>
            <button className="btn-shiny" onClick={() => navigate('/admin')}>
              Admin Panel
              <ExternalLink size={13} />
            </button>
          </div>
        </div>

        {/* Message Feeds */}
        <div className="messages-container">
          {messages.length === 1 && messages[0].role === 'assistant' && messages[0].text.startsWith("Hi! I'm Mera") ? (
            /* Welcome Empty State */
            <div className="welcome-container animate-fade-in">
              <div className="welcome-logo">M</div>
              <h2 className="welcome-title">I'm Mera, your travel assistant.</h2>
              <p className="welcome-sub">Ask me to look for hotels, suggest room features, or build an itinerary. Try choosing one of the prompt templates below:</p>
              
              <div className="suggested-prompts-grid">
                {suggestions.map((s, idx) => (
                  <div key={idx} className="prompt-card" onClick={() => handleSendMessage(s.text)}>
                    <div className="prompt-card-title">{s.title}</div>
                    <div className="prompt-card-desc">{s.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            /* Active Message List */
            <div className="chat-max-width">
              {messages.map((msg, index) => (
                <div key={index} className={`message-row ${msg.role === 'user' ? 'user' : 'assistant'}`} style={{ marginBottom: 32 }}>
                  <div className={`message-avatar ${msg.role}`}>
                    {msg.role === 'user' ? <User size={16} /> : <Sparkles size={16} />}
                  </div>
                  
                  <div className="message-content-wrapper">
                    <div className="message-sender">
                      {msg.role === 'user' ? 'You' : 'Mera'}
                    </div>
                    <div 
                      className="message-bubble"
                      dangerouslySetInnerHTML={{ __html: msg.role === 'user' ? msg.text : renderMarkdown(msg.text) }}
                    />
                  </div>
                </div>
              ))}

              {/* Waiting Dots indicator */}
              {loading && (
                <div className="message-row assistant" style={{ marginBottom: 32 }}>
                  <div className="message-avatar assistant">
                    <Sparkles size={16} />
                  </div>
                  <div className="message-content-wrapper">
                    <div className="message-sender">Mera</div>
                    <div className="dot-loading-container" style={{ marginTop: 6 }}>
                      <span className="loading-dot"></span>
                      <span className="loading-dot"></span>
                      <span className="loading-dot"></span>
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Box Row */}
        <div className="chat-input-container">
          <div className="chat-max-width">
            <div className="input-box-wrapper">
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                rows={1}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder="Message Mera... (e.g. Booking a trip to Goa this weekend)"
                disabled={loading}
              />
              <button 
                className="send-btn-circle" 
                onClick={() => handleSendMessage()}
                disabled={loading || !inputText.trim()}
              >
                <Send size={16} />
              </button>
            </div>
            <div className="input-disclaimer">
              Mera may display inaccurate information, including room prices. Verify reservation details before payment.
            </div>
          </div>
        </div>
      </div>

      {/* ================= RIGHT SIDEBAR (STATE & TOOLS) ================= */}
      {rightCollapsed ? (
        <div className="collapse-handle" onClick={() => setRightCollapsed(false)}>
          <ChevronLeft size={14} style={{ marginTop: 20 }} />
          <div className="vertical-text" style={{ marginTop: 'auto', marginBottom: 20 }}>BOOKING STATE</div>
        </div>
      ) : (
        <div className="panel panel-right shiny-texture">
          <div className="left-sidebar-header" style={{ borderBottom: '1px solid var(--border-glow)' }}>
            <button className="btn-shiny" style={{ padding: '4px 6px' }} onClick={() => setRightCollapsed(true)}>
              <ChevronRight size={16} />
            </button>
            <span className="sidebar-title">
              <Database size={16} />
              Booking State
            </span>
          </div>

          <div className="right-sidebar-content">
            {/* Parameters Grid */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">Extracted Details</div>
              <div className="state-grid-ui">
                {[
                  { label: "Destination", val: bookingState.destination },
                  { label: "Check-in Date", val: bookingState.check_in },
                  { label: "Check-out Date", val: bookingState.check_out },
                  { label: "Guests Count", val: bookingState.num_guests },
                  { label: "Budget per night", val: bookingState.budget_per_night_inr ? `₹${bookingState.budget_per_night_inr}` : null },
                  { label: "Preferences", val: (bookingState.room_preferences || []).join(', ') },
                  { label: "Amenities", val: (bookingState.amenities_wanted || []).join(', ') },
                  { label: "Selected Room", val: bookingState.selected_room_type },
                ].map((item, idx) => (
                  <div key={idx} className={`state-card ${item.val ? 'filled' : 'empty'}`}>
                    <span className="state-card-label">{item.label}</span>
                    <span className="state-card-value">{item.val || '—'}</span>
                  </div>
                ))}
              </div>
              
              {bookingState.stage && (
                <div style={{ marginTop: 14 }}>
                  <span className="model-badge" style={{ textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.05em', background: 'rgba(255,255,255,0.03)' }}>
                    Stage: {bookingState.stage}
                  </span>
                </div>
              )}
            </div>

            {/* Tool trace logs */}
            <div className="sidebar-section" style={{ flex: 1, borderBottom: 'none' }}>
              <div className="sidebar-section-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Terminal size={12} />
                Tool Call Trace
              </div>
              
              <div className="timeline">
                {traceLog.length > 0 ? (
                  traceLog.map((t, idx) => (
                    <div key={idx} className="timeline-item">
                      {t.type === 'error' ? (
                        <div className="timeline-item-header error">
                          <span>ERROR</span>
                        </div>
                      ) : (
                        <div className="timeline-item-header">
                          <span className="timeline-item-name">{t.tool}</span>
                          <span style={{ fontSize: 9, opacity: 0.7 }}>args</span>
                        </div>
                      )}
                      
                      <div className="timeline-item-body">
                        {t.type === 'error' ? (
                          t.message
                        ) : (
                          <div>
                            <div style={{ opacity: 0.5, marginBottom: 4 }}>INPUT: {JSON.stringify(t.input)}</div>
                            <div style={{ color: 'var(--text-primary)' }}>OUTPUT: {JSON.stringify(t.result)}</div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ color: 'var(--text-dim)', textAlign: 'center', fontSize: 12, padding: '20px 0' }}>
                    No tools executed in this turn.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

export default GuestView
