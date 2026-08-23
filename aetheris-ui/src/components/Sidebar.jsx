import { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import FocusTrap from 'focus-trap-react';
import { FixedSizeList } from 'react-window';
import { Plus, MessageSquare, Trash2, X, Search } from 'lucide-react';
import TriadMark from './TriadMark';
import { logout, getUserEmail } from '../utils/auth';

const VIRTUALIZATION_THRESHOLD = 50;
const ITEM_HEIGHT = 56;

function formatConversationTimestamp(timestamp) {
  const date = new Date(timestamp);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = date.toDateString() === yesterday.toDateString();

  if (isToday) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  if (isYesterday) {
    return 'Yesterday';
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function HighlightMatch({ text, query }) {
  if (!query) return text;

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const index = lowerText.indexOf(lowerQuery);

  if (index === -1) return text;

  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-accent-cyan/20 text-accent-cyan">{text.slice(index, index + query.length)}</mark>
      {text.slice(index + query.length)}
    </>
  );
}

function conversationMatchesQuery(conversation, query) {
  if (conversation.title.toLowerCase().includes(query)) return true;

  return conversation.messages.some((message) => {
    if (message.content?.toLowerCase().includes(query)) return true;
    return message.response?.answer?.toLowerCase().includes(query);
  });
}

function ConversationItem({ conversation, activeId, debouncedQuery, onSelect, onClose, setDeleteTarget }) {
  return (
    <button
      onClick={() => {
        onSelect(conversation.id);
        onClose?.();
      }}
      aria-current={conversation.id === activeId ? 'page' : undefined}
      className={`group flex w-full cursor-pointer items-center gap-2 rounded-xl px-3 py-2.5 text-sm transition-colors ${
        conversation.id === activeId
          ? 'border border-accent-cyan/20 bg-accent-cyan/10 text-slate-100'
          : 'text-slate-400 hover:bg-white/5'
      }`}
    >
      <MessageSquare className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-left">
        <span className="block truncate">
          <HighlightMatch text={conversation.title} query={debouncedQuery} />
        </span>
        <span className="mt-0.5 block text-[11px] text-slate-500" aria-hidden="true">
          {formatConversationTimestamp(conversation.createdAt)}
        </span>
      </div>
      <span
        role="button"
        tabIndex={0}
        onClick={(event) => {
          event.stopPropagation();
          setDeleteTarget(conversation.id);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.stopPropagation();
            event.preventDefault();
            setDeleteTarget(conversation.id);
          }
        }}
        aria-label={`Delete ${conversation.title}`}
        className="touch-target flex items-center justify-center text-slate-500 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100 md:opacity-0"
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
      </span>
    </button>
  );
}

export default function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, open, onClose }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const navRef = useRef(null);
  const [navHeight, setNavHeight] = useState(400);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setNavHeight(entry.contentRect.height);
      }
    });
    observer.observe(el);
    setNavHeight(el.clientHeight);
    return () => observer.disconnect();
  }, []);

  const filteredList = useMemo(() => {
    const sorted = Object.values(conversations).sort((a, b) => b.createdAt - a.createdAt);
    const query = debouncedQuery.toLowerCase();

    if (!query) return sorted;
    return sorted.filter((conversation) => conversationMatchesQuery(conversation, query));
  }, [conversations, debouncedQuery]);

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      onDelete(deleteTarget);
      setDeleteTarget(null);
    }
  };

  const isVirtualized = filteredList.length > VIRTUALIZATION_THRESHOLD;

  const Row = useCallback(
    ({ index, style }) => {
      const conversation = filteredList[index];
      return (
        <div style={style} className="px-1 py-0.5">
          <ConversationItem
            conversation={conversation}
            activeId={activeId}
            debouncedQuery={debouncedQuery}
            onSelect={onSelect}
            onClose={onClose}
            setDeleteTarget={setDeleteTarget}
          />
        </div>
      );
    },
    [filteredList, activeId, debouncedQuery, onSelect, onClose]
  );

  const sidebarContent = (
    <>
      <div className="mb-4 flex items-center gap-2 px-1">
        <TriadMark size={20} aria-hidden="true" />
        <span className="text-sm font-semibold tracking-wide text-slate-200">Calienne</span>
        <button
          onClick={onClose}
          className="btn-icon touch-target ml-auto md:hidden"
          aria-label="Close sidebar"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
        <input
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search conversations..."
          aria-label="Search conversations"
          className="input-search"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="btn-icon absolute right-2 top-1/2 -translate-y-1/2 touch-target p-1"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>

      <button
        onClick={() => {
          onNew();
          onClose?.();
        }}
        className="mb-3 flex touch-target w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-200 ring-1 ring-white/10 transition-colors hover:bg-white/5"
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        New conversation
      </button>

      <nav ref={navRef} aria-label="Conversations" className="flex-1 overflow-y-auto">
        {filteredList.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-slate-500" role="status">No results</p>
        ) : isVirtualized ? (
          <FixedSizeList
            height={navHeight}
            itemCount={filteredList.length}
            itemSize={ITEM_HEIGHT}
            width="100%"
          >
            {Row}
          </FixedSizeList>
        ) : (
          <div className="space-y-1">
            {filteredList.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                activeId={activeId}
                debouncedQuery={debouncedQuery}
                onSelect={onSelect}
                onClose={onClose}
                setDeleteTarget={setDeleteTarget}
              />
            ))}
          </div>
        )}
      </nav>

      <div className="glass-panel mt-3 rounded-xl px-3 py-2.5 text-[11px] text-slate-500">
        Conversations are stored locally in this browser.
      </div>

      <div className="mt-3 border-t border-white/5 pt-3">
        <div className="flex items-center justify-between rounded-xl px-2 py-1.5 text-xs text-slate-400">
          <span
            className="max-w-[140px] truncate font-medium text-slate-300"
            title={getUserEmail() || 'User'}
          >
            {getUserEmail() || 'User'}
          </span>
          <button
            onClick={logout}
            className="btn-ghost flex cursor-pointer items-center gap-1 text-xs font-semibold text-slate-400 hover:text-rose-400 px-2 py-1"
          >
            Log Out
          </button>
        </div>
      </div>
    </>
  );

  return (
    <>
      <aside className="hidden w-[280px] flex-col border-r border-white/5 bg-surface-800/60 p-3 md:flex" aria-label="Sidebar navigation">
        {sidebarContent}
      </aside>

      <AnimatePresence>
        {open && (
          <FocusTrap active={open}>
            <div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={onClose}
                className="fixed inset-0 z-40 bg-black/50 md:hidden"
                aria-hidden="true"
              />
              <motion.aside
                initial={{ x: '-100%' }}
                animate={{ x: 0 }}
                exit={{ x: '-100%' }}
                transition={{ type: 'spring', stiffness: 300, damping: 32 }}
                className="fixed left-0 top-0 z-50 flex h-full w-full flex-col border-r border-white/10 bg-surface-800/95 p-3 backdrop-blur-xl md:hidden"
                aria-label="Sidebar navigation"
              >
                {sidebarContent}
              </motion.aside>
            </div>
          </FocusTrap>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {deleteTarget && (
          <FocusTrap active={!!deleteTarget} focusTrapOptions={{ fallbackFocus: '#delete-dialog-title' }}>
            <div>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setDeleteTarget(null)}
                className="fixed inset-0 z-[60] bg-black/60"
                aria-hidden="true"
              />
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                role="dialog"
                aria-modal="true"
                aria-labelledby="delete-dialog-title"
                className="fixed left-1/2 top-1/2 z-[70] w-[min(90vw,24rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-white/10 bg-surface-800 p-5 shadow-xl"
              >
                <h2 id="delete-dialog-title" className="text-base font-semibold text-slate-100">
                  Delete conversation?
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  This action cannot be undone. The conversation will be permanently removed.
                </p>
                <div className="mt-5 flex justify-end gap-2">
                  <button
                    onClick={() => setDeleteTarget(null)}
                    className="btn-ghost text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmDelete}
                    className="btn-danger text-sm"
                  >
                    Delete
                  </button>
                </div>
              </motion.div>
            </div>
          </FocusTrap>
        )}
      </AnimatePresence>
    </>
  );
}
