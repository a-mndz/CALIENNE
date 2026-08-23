import { useState, useRef, useCallback, useEffect } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';

const MAX_CHARS = 4000;
const APPROACHING_THRESHOLD = 0.8;

/**
 * InputBox — message composition with auto-resize, keyboard shortcuts, and focus management.
 *
 * Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 11.5, 12.7
 */
export default function InputBox({ onSend, disabled, preservedText, onPreservedTextConsumed }) {
  const [value, setValue] = useState(preservedText || '');
  const textareaRef = useRef(null);

  useEffect(() => {
    if (preservedText) {
      setValue(preservedText);
      if (onPreservedTextConsumed) onPreservedTextConsumed();
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.style.height = 'auto';
        textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
      }
    }
  }, [preservedText, onPreservedTextConsumed]);

  const submit = useCallback(() => {
    if (!value.trim() || disabled) return;
    onSend(value);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.focus();
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (e) => {
    setValue(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
  };

  const charCount = value.length;
  const showCount = charCount > MAX_CHARS * APPROACHING_THRESHOLD;
  const isOverLimit = charCount > MAX_CHARS;

  return (
    <div className="border-t border-white/5 bg-surface-900/60 px-4 py-4 md:px-8">
      <div className={`mx-auto flex max-w-3xl items-end gap-2 rounded-2xl glass-panel input-glow px-3 py-2.5 transition-shadow duration-300 ${isOverLimit ? 'ring-1 ring-rose-400/40' : ''}`}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={autoGrow}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder="Ask Calienne anything…"
          aria-label="Message input"
          aria-disabled={disabled}
          className="flex-1 resize-none bg-transparent text-base text-slate-100 placeholder:text-slate-500 outline-none max-h-40"
        />
        <div className="flex items-center gap-2 flex-shrink-0">
          {showCount && (
            <span className={`text-[10px] font-mono tabular-nums ${isOverLimit ? 'text-rose-400' : 'text-slate-600'}`} aria-live="polite" aria-atomic="true">
              {charCount}/{MAX_CHARS}
            </span>
          )}
          <button
            onClick={submit}
            disabled={disabled || !value.trim() || isOverLimit}
            aria-label="Send query"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500 to-violet-500 text-white transition-all disabled:opacity-30 hover:shadow-glow active:scale-95"
          >
            {disabled ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowUp className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-500">
        Calienne reasons through a Logician and a Creative agent, reconciled by a Judge. Verify high-stakes answers independently.
      </p>
    </div>
  );
}
