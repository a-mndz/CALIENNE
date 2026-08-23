import { useEffect, useRef, useCallback, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FixedSizeList } from 'react-window';
import { Loader2 } from 'lucide-react';
import MessageBubble from './MessageBubble';
import EmptyState from './EmptyState';
import { messageVariants } from '../utils/animations';
import { useSettingsStore } from '../store/useSettingsStore';


const VIRTUALIZATION_THRESHOLD = 50;
const ITEM_ESTIMATED_HEIGHT = 120; // px per message row (approximate)

/**
 * StreamingIndicator — lightweight floating indicator shown when a pipeline is active.
 */
function StreamingIndicator({ stage }) {
  if (!stage || stage === 'idle' || stage === 'done' || stage === 'error') return null;
  const stageLabels = {
    breaker: 'Knowledge gate check',
    agents: 'Agent reasoning',
    judge: 'Judge synthesis',
  };
  return (
    <div className="flex justify-center py-2" role="status" aria-live="polite">
      <div className="inline-flex items-center gap-2 rounded-full glass-panel px-3 py-1.5 text-xs text-slate-400">
        <Loader2 className="h-3 w-3 animate-spin text-cyan-400" aria-hidden="true" />
        <span className="animate-thinking-pulse">{stageLabels[stage] || 'Processing'}…</span>
      </div>
    </div>
  );
}

/**
 * ChatWindow — scrollable message area with auto-scroll, virtualization, and empty state.
 *
 * Requirements: 1.5, 18.1, 18.2, 18.7, 13.5
 */
export default function ChatWindow({ messages, currentStage, agentStates, partialData, onSuggestion, onRetry, messageDensity, autoExpandReasoning }) {
  const bottomRef = useRef(null);
  const topRef = useRef(null);
  const listRef = useRef(null);
  const containerRef = useRef(null);
  const lastMessage = messages[messages.length - 1];
  const animationsEnabled = useSettingsStore((state) => state.animationsEnabled);
  const [listHeight, setListHeight] = useState(400);
  const densityGap = messageDensity === 'compact' ? 'gap-3' : 'gap-5';
  const densityPadding = messageDensity === 'compact' ? 'py-4' : 'py-6';

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setListHeight(entry.contentRect.height);
      }
    });
    observer.observe(el);
    setListHeight(el.clientHeight);
    return () => observer.disconnect();
  }, []);

  const handleKeyDown = useCallback((e) => {
    if (e.ctrlKey && e.key === 'Home') {
      e.preventDefault();
      if (messages.length > VIRTUALIZATION_THRESHOLD && listRef.current) {
        listRef.current.scrollToItem(0, 'start');
      } else {
        topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
    if (e.ctrlKey && e.key === 'End') {
      e.preventDefault();
      if (messages.length > VIRTUALIZATION_THRESHOLD && listRef.current) {
        listRef.current.scrollToItem(messages.length - 1, 'end');
      } else {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }
    }
  }, [messages.length]);

  useEffect(() => {
    if (messages.length > VIRTUALIZATION_THRESHOLD && listRef.current) {
      listRef.current.scrollToItem(messages.length - 1, 'end');
    } else {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages.length, lastMessage?.status, currentStage]);

  const isVirtualized = messages.length > VIRTUALIZATION_THRESHOLD;

  // Row renderer for react-window
  const Row = useCallback(
    ({ index, style }) => {
      const m = messages[index];
      return (
        <div style={style} className={`px-4 md:px-8 ${messageDensity === 'compact' ? 'py-1' : 'py-2'}`}>
          <MessageBubble
            message={m}
            currentStage={currentStage}
            agentStates={agentStates}
            partialData={partialData}
            isLatest={index === messages.length - 1 || index === messages.length - 2}
            onRetry={onRetry}
            autoExpand={autoExpandReasoning}
          />
        </div>
      );
    },
    [messages, currentStage, agentStates, partialData, onRetry, messageDensity, autoExpandReasoning]
  );

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto"
      role="log"
      aria-label="Conversation messages"
      aria-live="polite"
      aria-relevant="additions"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div ref={topRef} />
      <AnimatePresence mode="wait">
        {messages.length === 0 ? (
          <EmptyState key="empty" onSuggestion={onSuggestion} />
        ) : (
          <motion.div
            key="messages"
            initial={false}
            animate={{ opacity: 1 }}
            className="h-full"
          >
            {isVirtualized ? (
              <FixedSizeList
                ref={listRef}
                height={listHeight}
                itemCount={messages.length}
                itemSize={ITEM_ESTIMATED_HEIGHT}
                width="100%"
                className="scrollbar-thin"
              >
                {Row}
              </FixedSizeList>
            ) : (
              <div className={`mx-auto flex max-w-3xl flex-col ${densityGap} px-4 ${densityPadding} md:px-8`}>
                {messages.map((m, i) => (
                  <motion.div
                    key={m.id}
                    initial={animationsEnabled ? 'hidden' : false}
                    animate={animationsEnabled ? 'visible' : false}
                    variants={messageVariants}
                  >
                    <MessageBubble
                      message={m}
                      currentStage={currentStage}
                      agentStates={agentStates}
                      partialData={partialData}
                      isLatest={i === messages.length - 1 || i === messages.length - 2}
                      onRetry={onRetry}
                      autoExpand={autoExpandReasoning}
                    />
                  </motion.div>
                ))}
                <div ref={bottomRef} />
              </div>
            )}

            <StreamingIndicator stage={currentStage} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
