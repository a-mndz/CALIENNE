import { create } from 'zustand';

function createId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// The backend spec defines no conversation-persistence endpoint, so chat
// history is persisted client-side. This is explicitly an assumption filling
// a gap in the given contract — see README "Assumptions & Gaps".
function getStorageKey() {
  const email = localStorage.getItem('user_email') || 'anonymous';
  return `calienne.conversations.${email}.v1`;
}

function loadPersisted() {
  try {
    const raw = localStorage.getItem(getStorageKey());
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function persist(payload) {
  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(payload));
  } catch {
    // localStorage unavailable (private browsing / quota exceeded) —
    // fail silently; in-memory state still functions for this session.
  }
}

function deriveTitle(query) {
  const trimmed = query.trim();
  return trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed || 'New conversation';
}

const persisted = loadPersisted();
const initialId = persisted?.activeId ?? createId();
const initialConversations =
  persisted?.conversations ??
  {
    [initialId]: { id: initialId, title: 'New conversation', createdAt: Date.now(), messages: [] },
  };

export const useChatStore = create((set, get) => ({
  conversations: initialConversations,
  activeId: initialId,
  telemetry: [],
  providerHealth: [],

  newConversation: () => {
    const id = createId();
    set((state) => {
      const conversations = {
        ...state.conversations,
        [id]: { id, title: 'New conversation', createdAt: Date.now(), messages: [] },
      };
      persist({ conversations, activeId: id });
      return { conversations, activeId: id };
    });
  },

  selectConversation: (id) => {
    set((state) => {
      persist({ conversations: state.conversations, activeId: id });
      return { activeId: id };
    });
  },

  deleteConversation: (id) => {
    set((state) => {
      const conversations = { ...state.conversations };
      delete conversations[id];

      let activeId = state.activeId;
      if (activeId === id) {
        const remaining = Object.keys(conversations);
        if (remaining.length === 0) {
          const newId = createId();
          conversations[newId] = { id: newId, title: 'New conversation', createdAt: Date.now(), messages: [] };
          activeId = newId;
        } else {
          activeId = remaining[0];
        }
      }
      persist({ conversations, activeId });
      return { conversations, activeId };
    });
  },

  addMessage: (conversationId, message) => {
    set((state) => {
      const conversation = state.conversations[conversationId];
      if (!conversation) return {};
      const isFirstUserMessage = conversation.messages.length === 0 && message.role === 'user';
      const updatedConversation = {
        ...conversation,
        title: isFirstUserMessage ? deriveTitle(message.content) : conversation.title,
        messages: [...conversation.messages, message],
      };
      const conversations = { ...state.conversations, [conversationId]: updatedConversation };
      persist({ conversations, activeId: state.activeId });
      return { conversations };
    });
  },

  updateMessage: (conversationId, messageId, patch) => {
    set((state) => {
      const conversation = state.conversations[conversationId];
      if (!conversation) return {};
      const messages = conversation.messages.map((m) => (m.id === messageId ? { ...m, ...patch } : m));
      const conversations = { ...state.conversations, [conversationId]: { ...conversation, messages } };
      persist({ conversations, activeId: state.activeId });
      return { conversations };
    });
  },

  addTelemetryEntry: (entry) => {
    set((state) => ({ telemetry: [entry, ...state.telemetry].slice(0, 100) }));
  },

  setProviderHealth: (next) => set({ providerHealth: next }),

  getActiveConversation: () => {
    const state = get();
    return state.conversations[state.activeId];
  },
}));
