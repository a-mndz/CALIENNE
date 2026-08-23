import { useEffect } from "react";
import { Send, Square } from "lucide-react";
import { MAX_MESSAGE_CHARS } from "../constants/input.js";

function ChatInputBar({
  value, onChange, onSend, onStop, streaming, inputRef,
}) {
  useEffect(() => {
    const ta = inputRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }, [value, inputRef]);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!streaming && !overLimit) onSend();
    }
  }
  const overLimit = value.length > MAX_MESSAGE_CHARS;

  return (
    <div className="input-bar">
      <div className="input-bar-inner">
        <div className="input-row">
          <label htmlFor="calienne-input" className="sr-only">Ask Calienne anything</label>
          <textarea
            id="calienne-input"
            ref={inputRef}
            rows={1}
            placeholder="Ask Calienne anything..."
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            maxLength={MAX_MESSAGE_CHARS}
            aria-label="Message Calienne"
          />
          {streaming ? (
            <button className="send-btn stop" onClick={onStop} aria-label="Stop generating">
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button className="send-btn" onClick={onSend} disabled={!value.trim() || overLimit} aria-label="Send message">
              <Send size={16} />
            </button>
          )}
        </div>
        <div className="input-controls">
          <span className="input-capability">Automatic routing</span>
          <span className={`char-count${overLimit ? " near-limit" : ""}`}>{value.length}/{MAX_MESSAGE_CHARS}</span>
        </div>
        <div className="input-hint">Enter to send // Shift+Enter for newline // <kbd>/</kbd> to focus</div>
      </div>
    </div>
  );
}

export default ChatInputBar;
