import { useRef, useEffect, useState } from "react";
import { Copy, ChevronLeft, Check } from "lucide-react";
import { AGENTS } from "../constants/agents.js";
import { copyTextToClipboard } from "../utils/clipboard.js";
import TypingDots from "./TypingDots.jsx";
import FormattedMessage from "./FormattedMessage.jsx";

function HitlClarificationCard({ message, onResume }) {
  const [val, setVal] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSend() {
    if (!val.trim() || submitting || !onResume) return;
    setSubmitting(true);
    try {
      await onResume(message.traceId, val.trim());
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="msg-paused-card">
      <div className="msg-paused-head">
        <span className="msg-paused-tag">⏸ Human Clarification Required</span>
        <span className="msg-paused-trace">TRACE: {message.traceId ? String(message.traceId).slice(0, 8) : "—"}</span>
      </div>
      <div className="msg-paused-question">{message.question || message.text}</div>
      {message.resumed ? (
        <div className="msg-paused-resumed">
          <Check size={14} className="text-ok" />
          <span>Resumed with: <strong>{message.resumeValue}</strong></span>
        </div>
      ) : (
        <div className="msg-paused-input-row">
          <input
            type="text"
            className="msg-paused-input"
            placeholder="Type clarification to resume execution..."
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={submitting}
          />
          <button
            type="button"
            className="msg-paused-btn"
            onClick={handleSend}
            disabled={!val.trim() || submitting}
          >
            {submitting ? "Resuming..." : "Resume Run"}
          </button>
        </div>
      )}
    </div>
  );
}

function ChatThread({ messages, typingAgent, title, mode, agentsCount, pushToast, onBack, isNarrow, onResume }) {
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, typingAgent]);

  async function copyText(text) {
    try {
      await copyTextToClipboard(text);
      pushToast("Copied to clipboard");
    } catch {
      pushToast("Clipboard copy failed", "error");
    }
  }

  return (
    <div className="thread">
      <div className="thread-header">
        <div className="thread-header-main">
          {isNarrow && <button className="thread-back mobile-only" onClick={onBack} aria-label="Back to conversations"><ChevronLeft size={15} /></button>}
          <div className="thread-title-wrap">
            <div className="thread-title">{title}</div>
            <div className="thread-meta">
              <span className="thread-badge">{mode}</span>
              <span className="thread-meta-text">{agentsCount} agents</span>
            </div>
          </div>
        </div>
      </div>
      <div className="thread-body" aria-live="polite" aria-relevant="additions">
        {messages.map((m, i) => {
          if (m.role === "paused") {
            return (
              <div className="msg msg-paused" key={m.id || i}>
                <HitlClarificationCard message={m} onResume={onResume} />
              </div>
            );
          }
          if (m.role === "user") {
            return (
              <div className="msg msg-user" key={m.id || i}>
                <div className="msg-row">
                  <button className="msg-copy" onClick={() => copyText(m.text)} aria-label="Copy message"><Copy size={12} /></button>
                  <div className="msg-bubble user-bubble">{m.text}</div>
                </div>
              </div>
            );
          }
          const agent = (() => {
            const str = String(m.agentId || "Agent");
            const found = AGENTS.find((a) => a.id.toLowerCase() === str.toLowerCase() || a.name.toLowerCase() === str.toLowerCase());
            if (found) return found;
            const code = str.slice(0, 3).toUpperCase();
            return { code, name: str, color: str.toLowerCase() === "synthesis" ? "var(--c-red)" : "var(--text-dim)" };
          })();
          return (
            <div className="msg msg-agent" key={m.id || i} style={{ "--agent-color": agent?.color }}>
              <div className="msg-avatar">{agent?.icon ? <agent.icon size={13} /> : <span style={{ fontSize: 9 }}>{agent.code}</span>}</div>
              <div>
                <div className="msg-agent-name">{agent.code} // {agent.name}</div>
                <div className="msg-row">
                  <div className="msg-bubble agent-bubble">
                    <FormattedMessage text={m.text} pushToast={pushToast} />
                  </div>
                  <button className="msg-copy" onClick={() => copyText(m.text)} aria-label="Copy message"><Copy size={12} /></button>
                </div>
              </div>
            </div>
          );
        })}
        {typingAgent && (() => {
          const str = String(typingAgent);
          const agent = AGENTS.find((a) => a.id.toLowerCase() === str.toLowerCase() || a.name.toLowerCase() === str.toLowerCase()) || { code: str.slice(0, 3).toUpperCase(), name: str, color: "var(--text-dim)" };
          return (
            <div className="msg msg-agent" style={{ "--agent-color": agent?.color }}>
              <div className="msg-avatar">{agent?.icon ? <agent.icon size={13} /> : <span style={{ fontSize: 9 }}>{agent.code}</span>}</div>
              <div>
                <div className="msg-agent-name">{agent.code} // {agent.name}</div>
                <div className="msg-bubble typing"><TypingDots /></div>
              </div>
            </div>
          );
        })()}
        <div ref={endRef} />
      </div>
    </div>
  );
}

export default ChatThread;
