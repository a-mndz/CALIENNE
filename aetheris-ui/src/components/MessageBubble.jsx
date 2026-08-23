import { memo, useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, AlertTriangle, Bot, Copy, Check, Eye, EyeOff, RotateCcw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ConfidenceBadge from './ConfidenceBadge';
import BiasRiskBadge from './BiasRiskBadge';
import ReasoningPanel from './ReasoningPanel';
import PipelineStatus from './PipelineStatus';
import AgentStreamCard from './AgentStreamCard';
import { highlight } from '../utils/syntaxHighlight';

/**
 * Format a timestamp into a readable relative time.
 */
function formatTimestamp(ts) {
  const date = new Date(ts);
  const now = new Date();
  const diff = now - date;
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * CopyButton — copies text to clipboard with visual feedback.
 */
function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="btn-pill touch-target text-slate-300"
      aria-label={copied ? 'Copied to clipboard' : 'Copy answer to clipboard'}
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-emerald-400" aria-hidden="true" />
          Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" aria-hidden="true" />
          Copy
        </>
      )}
    </button>
  );
}

/**
 * CodeBlock — custom renderer for fenced code blocks in ReactMarkdown.
 * Provides syntax highlighting and a language label.
 *
 * Requirements: 18.4 (syntax-highlight code blocks based on language)
 */
function CodeBlock({ children, className, inline }) {
  if (inline) {
    return (
      <code className="bg-white/[0.08] px-1.5 py-0.5 rounded text-[0.875em] font-mono text-slate-200">
        {children}
      </code>
    );
  }

  const raw = String(children).replace(/\n$/, '');
  const langMatch = /language-(\w+)/.exec(className || '');
  const language = langMatch ? langMatch[1] : '';
  const html = useMemo(() => highlight(raw, language), [raw, language]);

  return (
    <div className="my-3">
      {language && (
        <div className="code-block-header">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            {language}
          </span>
        </div>
      )}
      <pre className="overflow-x-auto">
        <code
          className={`font-mono text-sm leading-relaxed ${language ? `language-${language}` : ''}`}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </pre>
    </div>
  );
}

/**
 * MessageBubble — renders an individual chat message with reasoning panel.
 *
 * Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 12.6, 13.4
 */
const MessageBubble = memo(function MessageBubble({
  message,
  currentStage,
  partialData,
  agentStates,
  isLatest,
  onRetry,
  autoExpand,
}) {
  const [reasoningOpen, setReasoningOpen] = useState(isLatest || !!autoExpand);
  const [showTimestamp, setShowTimestamp] = useState(false);

  const handleToggleReasoning = useCallback(() => {
    setReasoningOpen((v) => !v);
  }, []);

  const handleMouseEnter = useCallback(() => setShowTimestamp(true), []);
  const handleMouseLeave = useCallback(() => setShowTimestamp(false), []);

  if (message.role === 'user') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="flex justify-end group"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <div className="relative max-w-[75%]">
          <div className="rounded-2xl rounded-tr-sm bg-gradient-to-br from-violet-600/80 to-cyan-600/60 px-4 py-2.5 text-sm text-white shadow-lg">
            {message.content}
          </div>
          <AnimatePresence>
            {showTimestamp && (
              <motion.span
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 4 }}
                transition={{ duration: 0.15 }}
                className="absolute right-0 -bottom-5 text-[10px] text-slate-500 whitespace-nowrap"
                aria-hidden="true"
              >
                {formatTimestamp(message.createdAt)}
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    );
  }

  // Check if we have partial agent outputs from the SSE stream
  const hasPartialAgents = message.status === 'pending' && partialData?.agent_outputs;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex gap-3 group"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div className="mt-1 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500/20 to-violet-500/20 ring-1 ring-white/10" aria-hidden="true">
        <Bot className="h-4 w-4 text-cyan-300" />
      </div>

      <div className="relative max-w-[85%] flex-1 min-w-0">
        {/* Timestamp on hover */}
        <AnimatePresence>
          {showTimestamp && (
            <motion.span
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.15 }}
              className="absolute -top-5 left-0 text-[10px] text-slate-500 whitespace-nowrap"
            >
              {formatTimestamp(message.createdAt)}
            </motion.span>
          )}
        </AnimatePresence>

        {/* Pending State — Pipeline Progress + Live Agent Cards + Thinking indicator */}
        {message.status === 'pending' && (
          <div className="rounded-2xl glass-panel px-4 py-3 space-y-3">
            {/* Thinking indicator */}
            <div className="flex items-center gap-2 text-xs text-slate-400 animate-thinking-pulse">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-500" />
              </span>
              <span className="font-medium text-cyan-300/80">Thinking…</span>
              <span className="text-slate-600">· {currentStage || 'Processing'}</span>
            </div>

            <PipelineStatus stage={currentStage} agentStates={agentStates} />

            {/* Live per-agent streaming cards */}
            {agentStates && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {['Breaker', 'Logician', 'Creative', 'Judge'].map((name) => (
                  <AgentStreamCard key={name} name={name} agent={agentStates[name]} />
                ))}
              </div>
            )}

            {/* Fallback: show partial agent outputs if no agentStates (legacy) */}
            {!agentStates && hasPartialAgents && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                transition={{ duration: 0.3 }}
              >
                <ReasoningPanel
                  response={partialData}
                  expanded={true}
                />
              </motion.div>
            )}
          </div>
        )}

        {/* Error State */}
        {message.status === 'error' && (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 px-4 py-3 text-sm text-rose-200" role="alert">
            <div className="flex items-center gap-2 font-medium mb-1">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              Pipeline failed
            </div>
            <p className="text-rose-300/90">{message.error}</p>
            {onRetry && (
              <button
                onClick={onRetry}
                className="btn-pill touch-target mt-2 text-rose-300 ring-rose-400/20 bg-rose-500/10 hover:bg-rose-500/20"
                aria-label="Retry failed query"
              >
                <RotateCcw className="h-3 w-3" aria-hidden="true" />
                Retry
              </button>
            )}
          </div>
        )}

        {/* Done State — Answer + Reasoning */}
        {message.status === 'done' && message.response && (
          <div className="rounded-2xl glass-panel px-4 py-3.5 gradient-border">
            {/* Answer with Markdown Rendering + Syntax Highlighting */}
            <div className="prose-calienne text-[0.95rem] text-slate-100">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code: CodeBlock,
                }}
              >
                {message.response.answer || ''}
              </ReactMarkdown>
            </div>

            {/* Metadata Bar */}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <ConfidenceBadge score={message.response.confidence_score} />
              <BiasRiskBadge risk={message.response.bias_risk} />

              <div className="ml-auto flex items-center gap-1.5">
                <CopyButton text={message.response.answer || ''} />

                <button
                  onClick={handleToggleReasoning}
                  className="btn-pill touch-target text-slate-300"
                  aria-expanded={reasoningOpen}
                  aria-controls={`reasoning-panel-${message.id}`}
                >
                  {reasoningOpen ? (
                    <>
                      <EyeOff className="h-3 w-3" aria-hidden="true" />
                      Hide reasoning
                    </>
                  ) : (
                    <>
                      <Eye className="h-3 w-3" aria-hidden="true" />
                      View reasoning
                    </>
                  )}
                  <ChevronDown
                    className={`h-3 w-3 transition-transform duration-200 ${reasoningOpen ? 'rotate-180' : ''}`}
                    aria-hidden="true"
                  />
                </button>
              </div>
            </div>

            <div id={`reasoning-panel-${message.id}`}>
              <ReasoningPanel
                response={message.response}
                expanded={reasoningOpen}
              />
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
}, (prev, next) => {
  if (prev.message.id !== next.message.id) return false;
  if (prev.isLatest !== next.isLatest) return false;
  if (prev.message.status !== next.message.status) return false;
  if (prev.message.content !== next.message.content) return false;
  if (prev.message.error !== next.message.error) return false;
  if (prev.message.createdAt !== next.message.createdAt) return false;
  if (prev.currentStage !== next.currentStage) return false;
  if (prev.autoExpand !== next.autoExpand) return false;
  const prevAnswer = prev.message.response?.answer;
  const nextAnswer = next.message.response?.answer;
  if (prevAnswer !== nextAnswer) return false;
  const prevConf = prev.message.response?.confidence_score;
  const nextConf = next.message.response?.confidence_score;
  if (prevConf !== nextConf) return false;
  return true;
});

export default MessageBubble;
