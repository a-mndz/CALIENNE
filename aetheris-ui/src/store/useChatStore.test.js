import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useChatStore } from './useChatStore.js';

describe('useChatStore', () => {
  beforeEach(() => {
    // Clear localStorage
    localStorage.clear();
    localStorage.getItem.mockClear();
    localStorage.setItem.mockClear();
    
    // Reset store to initial state
    const store = useChatStore.getState();
    const initialId = Object.keys(store.conversations)[0];
    useChatStore.setState({
      conversations: {
        [initialId]: {
          id: initialId,
          title: 'New conversation',
          createdAt: Date.now(),
          messages: [],
        },
      },
      activeId: initialId,
      telemetry: [],
      providerHealth: [],
    });
  });

  describe('initialization', () => {
    it('should initialize with one empty conversation', () => {
      const state = useChatStore.getState();
      
      expect(Object.keys(state.conversations)).toHaveLength(1);
      expect(state.activeId).toBeDefined();
      expect(state.conversations[state.activeId].messages).toEqual([]);
      expect(state.telemetry).toEqual([]);
      expect(state.providerHealth).toEqual([]);
    });

    it('should set active conversation to initial conversation', () => {
      const state = useChatStore.getState();
      
      expect(state.activeId).toBe(Object.keys(state.conversations)[0]);
    });
  });

  describe('newConversation', () => {
    it('should create a new conversation', () => {
      const { newConversation } = useChatStore.getState();
      const initialCount = Object.keys(useChatStore.getState().conversations).length;
      
      newConversation();
      
      const state = useChatStore.getState();
      expect(Object.keys(state.conversations)).toHaveLength(initialCount + 1);
    });

    it('should set new conversation as active', () => {
      const { newConversation } = useChatStore.getState();
      
      newConversation();
      
      const state = useChatStore.getState();
      const activeConversation = state.conversations[state.activeId];
      expect(activeConversation).toBeDefined();
      expect(activeConversation.title).toBe('New conversation');
    });

    it('should initialize new conversation with empty messages', () => {
      const { newConversation } = useChatStore.getState();
      
      newConversation();
      
      const state = useChatStore.getState();
      const activeConversation = state.conversations[state.activeId];
      expect(activeConversation.messages).toEqual([]);
    });

    it('should persist conversation to localStorage', () => {
      const { newConversation } = useChatStore.getState();
      
      newConversation();
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });
  });

  describe('selectConversation', () => {
    it('should switch active conversation', () => {
      const { newConversation, selectConversation } = useChatStore.getState();
      
      newConversation();
      const newId = useChatStore.getState().activeId;
      
      const conversations = useChatStore.getState().conversations;
      const otherIds = Object.keys(conversations).filter(id => id !== newId);
      const otherId = otherIds[0];
      
      selectConversation(otherId);
      
      expect(useChatStore.getState().activeId).toBe(otherId);
    });

    it('should persist active conversation selection', () => {
      const { newConversation, selectConversation } = useChatStore.getState();
      
      newConversation();
      const conversations = useChatStore.getState().conversations;
      const ids = Object.keys(conversations);
      
      selectConversation(ids[0]);
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });
  });

  describe('deleteConversation', () => {
    it('should remove conversation from store', () => {
      const { newConversation, deleteConversation } = useChatStore.getState();
      
      newConversation();
      const idToDelete = useChatStore.getState().activeId;
      
      deleteConversation(idToDelete);
      
      const state = useChatStore.getState();
      expect(state.conversations[idToDelete]).toBeUndefined();
    });

    it('should create new conversation if deleting the last one', () => {
      const state = useChatStore.getState();
      const onlyId = state.activeId;
      const { deleteConversation } = useChatStore.getState();
      
      deleteConversation(onlyId);
      
      const newState = useChatStore.getState();
      expect(Object.keys(newState.conversations)).toHaveLength(1);
      expect(newState.conversations[onlyId]).toBeUndefined();
    });

    it('should switch to another conversation if deleting active conversation', () => {
      const { newConversation, deleteConversation } = useChatStore.getState();
      
      newConversation();
      const conversations = useChatStore.getState().conversations;
      const ids = Object.keys(conversations);
      expect(ids).toHaveLength(2);
      
      const activeId = useChatStore.getState().activeId;
      deleteConversation(activeId);
      
      const newState = useChatStore.getState();
      expect(newState.activeId).not.toBe(activeId);
      expect(newState.conversations[newState.activeId]).toBeDefined();
    });

    it('should persist deletion to localStorage', () => {
      const { deleteConversation } = useChatStore.getState();
      const activeId = useChatStore.getState().activeId;
      
      deleteConversation(activeId);
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });
  });

  describe('addMessage', () => {
    it('should add message to conversation', () => {
      const state = useChatStore.getState();
      const { addMessage } = state;
      const message = {
        id: 'msg-1',
        role: 'user',
        content: 'Hello',
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      expect(conversation.messages).toHaveLength(1);
      expect(conversation.messages[0]).toEqual(message);
    });

    it('should update conversation title on first user message', () => {
      const state = useChatStore.getState();
      const { addMessage } = state;
      const message = {
        id: 'msg-1',
        role: 'user',
        content: 'What is quantum computing?',
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      expect(conversation.title).toBe('What is quantum computing?');
    });

    it('should truncate long titles to 48 characters', () => {
      const state = useChatStore.getState();
      const { addMessage } = state;
      const longContent = 'a'.repeat(60);
      const message = {
        id: 'msg-1',
        role: 'user',
        content: longContent,
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      expect(conversation.title).toHaveLength(49); // 48 chars + ellipsis
      expect(conversation.title.endsWith('…')).toBe(true);
    });

    it('should not update title for subsequent messages', () => {
      const state = useChatStore.getState();
      const { addMessage } = state;
      
      addMessage(state.activeId, {
        id: 'msg-1',
        role: 'user',
        content: 'First message',
        createdAt: Date.now(),
      });
      
      addMessage(state.activeId, {
        id: 'msg-2',
        role: 'assistant',
        content: 'Response',
        createdAt: Date.now(),
      });
      
      addMessage(state.activeId, {
        id: 'msg-3',
        role: 'user',
        content: 'Second user message',
        createdAt: Date.now(),
      });
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      expect(conversation.title).toBe('First message');
    });

    it('should persist message to localStorage', () => {
      const state = useChatStore.getState();
      const { addMessage } = state;
      const message = {
        id: 'msg-1',
        role: 'user',
        content: 'Hello',
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });

    it('should handle adding to non-existent conversation', () => {
      const { addMessage } = useChatStore.getState();
      const message = {
        id: 'msg-1',
        role: 'user',
        content: 'Hello',
        createdAt: Date.now(),
      };
      
      addMessage('non-existent-id', message);
      
      // Should not throw, and state should remain unchanged
      const state = useChatStore.getState();
      expect(state.conversations['non-existent-id']).toBeUndefined();
    });
  });

  describe('updateMessage', () => {
    it('should update message properties', () => {
      const state = useChatStore.getState();
      const { addMessage, updateMessage } = state;
      
      const message = {
        id: 'msg-1',
        role: 'assistant',
        status: 'pending',
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      updateMessage(state.activeId, 'msg-1', {
        status: 'done',
        response: {
          answer: 'This is the answer',
          confidence_score: 0.85,
        },
      });
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      const updatedMessage = conversation.messages.find(m => m.id === 'msg-1');
      
      expect(updatedMessage.status).toBe('done');
      expect(updatedMessage.response.answer).toBe('This is the answer');
      expect(updatedMessage.response.confidence_score).toBe(0.85);
    });

    it('should preserve existing message properties', () => {
      const state = useChatStore.getState();
      const { addMessage, updateMessage } = state;
      
      const message = {
        id: 'msg-1',
        role: 'assistant',
        status: 'pending',
        createdAt: Date.now(),
      };
      
      addMessage(state.activeId, message);
      
      updateMessage(state.activeId, 'msg-1', {
        status: 'done',
      });
      
      const updatedState = useChatStore.getState();
      const conversation = updatedState.conversations[state.activeId];
      const updatedMessage = conversation.messages.find(m => m.id === 'msg-1');
      
      expect(updatedMessage.role).toBe('assistant');
      expect(updatedMessage.createdAt).toBe(message.createdAt);
    });

    it('should persist update to localStorage', () => {
      const state = useChatStore.getState();
      const { addMessage, updateMessage } = state;
      
      addMessage(state.activeId, {
        id: 'msg-1',
        role: 'assistant',
        status: 'pending',
        createdAt: Date.now(),
      });
      
      localStorage.setItem.mockClear();
      
      updateMessage(state.activeId, 'msg-1', { status: 'done' });
      
      expect(localStorage.setItem).toHaveBeenCalled();
    });

    it('should handle updating non-existent message', () => {
      const state = useChatStore.getState();
      const { updateMessage } = state;
      
      updateMessage(state.activeId, 'non-existent-msg', { status: 'done' });
      
      // Should not throw
      const updatedState = useChatStore.getState();
      expect(updatedState.conversations[state.activeId].messages).toEqual([]);
    });

    it('should handle updating message in non-existent conversation', () => {
      const { updateMessage } = useChatStore.getState();
      
      updateMessage('non-existent-id', 'msg-1', { status: 'done' });
      
      // Should not throw, and state should remain unchanged
      const state = useChatStore.getState();
      expect(state.conversations['non-existent-id']).toBeUndefined();
    });
  });

  describe('addTelemetryEntry', () => {
    it('should add telemetry entry', () => {
      const { addTelemetryEntry } = useChatStore.getState();
      const entry = {
        id: 'tel-1',
        timestamp: Date.now(),
        query: 'Test query',
        latencyMs: 1500,
        confidence: 0.85,
      };
      
      addTelemetryEntry(entry);
      
      const state = useChatStore.getState();
      expect(state.telemetry).toHaveLength(1);
      expect(state.telemetry[0]).toEqual(entry);
    });

    it('should add newest entries to the beginning', () => {
      const { addTelemetryEntry } = useChatStore.getState();
      
      addTelemetryEntry({ id: '1', timestamp: 1000 });
      addTelemetryEntry({ id: '2', timestamp: 2000 });
      addTelemetryEntry({ id: '3', timestamp: 3000 });
      
      const state = useChatStore.getState();
      expect(state.telemetry[0].id).toBe('3');
      expect(state.telemetry[1].id).toBe('2');
      expect(state.telemetry[2].id).toBe('1');
    });

    it('should limit telemetry to 100 entries', () => {
      const { addTelemetryEntry } = useChatStore.getState();
      
      // Add 110 entries
      for (let i = 0; i < 110; i++) {
        addTelemetryEntry({ id: `tel-${i}`, timestamp: Date.now() + i });
      }
      
      const state = useChatStore.getState();
      expect(state.telemetry).toHaveLength(100);
      expect(state.telemetry[0].id).toBe('tel-109'); // Most recent
    });
  });

  describe('setProviderHealth', () => {
    it('should set provider health status', () => {
      const { setProviderHealth } = useChatStore.getState();
      const providers = [
        { name: 'Groq', status: 'online' },
        { name: 'OpenRouter', status: 'offline' },
      ];
      
      setProviderHealth(providers);
      
      const state = useChatStore.getState();
      expect(state.providerHealth).toEqual(providers);
    });

    it('should replace previous provider health data', () => {
      const { setProviderHealth } = useChatStore.getState();
      
      setProviderHealth([{ name: 'Groq', status: 'online' }]);
      setProviderHealth([{ name: 'OpenRouter', status: 'online' }]);
      
      const state = useChatStore.getState();
      expect(state.providerHealth).toHaveLength(1);
      expect(state.providerHealth[0].name).toBe('OpenRouter');
    });
  });

  describe('getActiveConversation', () => {
    it('should return active conversation', () => {
      const state = useChatStore.getState();
      const { getActiveConversation } = state;
      
      const activeConversation = getActiveConversation();
      
      expect(activeConversation).toBeDefined();
      expect(activeConversation.id).toBe(state.activeId);
    });

    it('should return updated conversation after adding message', () => {
      const { addMessage, getActiveConversation } = useChatStore.getState();
      const activeId = useChatStore.getState().activeId;
      
      addMessage(activeId, {
        id: 'msg-1',
        role: 'user',
        content: 'Test',
        createdAt: Date.now(),
      });
      
      const activeConversation = getActiveConversation();
      
      expect(activeConversation.messages).toHaveLength(1);
    });
  });

  describe('localStorage persistence', () => {
    it('should use user email in storage key', () => {
      localStorage.getItem.mockImplementation((key) => {
        if (key === 'user_email') return 'user@example.com';
        return null;
      });
      
      const { newConversation } = useChatStore.getState();
      newConversation();
      
      const calls = localStorage.setItem.mock.calls;
      const storageKey = calls[calls.length - 1]?.[0];
      expect(storageKey).toContain('user@example.com');
    });

    it('should use "anonymous" if no user email is set', () => {
      localStorage.getItem.mockReturnValue(null);
      
      const { newConversation } = useChatStore.getState();
      newConversation();
      
      const calls = localStorage.setItem.mock.calls;
      const storageKey = calls[calls.length - 1]?.[0];
      expect(storageKey).toContain('anonymous');
    });

    it('should persist conversations and activeId together', () => {
      const { newConversation } = useChatStore.getState();
      
      newConversation();
      
      const calls = localStorage.setItem.mock.calls;
      const lastCall = calls[calls.length - 1];
      const persistedData = JSON.parse(lastCall[1]);
      
      expect(persistedData).toHaveProperty('conversations');
      expect(persistedData).toHaveProperty('activeId');
    });
  });

  describe('complex conversation flow', () => {
    it('should handle complete conversation lifecycle', () => {
      const {
        newConversation,
        addMessage,
        updateMessage,
        selectConversation,
        deleteConversation,
      } = useChatStore.getState();
      
      // Create first conversation and add messages
      const firstId = useChatStore.getState().activeId;
      
      addMessage(firstId, {
        id: 'msg-1',
        role: 'user',
        content: 'First question',
        createdAt: Date.now(),
      });
      
      addMessage(firstId, {
        id: 'msg-2',
        role: 'assistant',
        status: 'pending',
        createdAt: Date.now(),
      });
      
      updateMessage(firstId, 'msg-2', {
        status: 'done',
        response: { answer: 'First answer' },
      });
      
      // Create second conversation
      newConversation();
      const secondId = useChatStore.getState().activeId;
      
      addMessage(secondId, {
        id: 'msg-3',
        role: 'user',
        content: 'Second question',
        createdAt: Date.now(),
      });
      
      // Switch back to first conversation
      selectConversation(firstId);
      
      expect(useChatStore.getState().activeId).toBe(firstId);
      
      // Delete second conversation
      deleteConversation(secondId);
      
      const finalState = useChatStore.getState();
      expect(finalState.conversations[secondId]).toBeUndefined();
      expect(finalState.conversations[firstId]).toBeDefined();
      expect(finalState.conversations[firstId].messages).toHaveLength(2);
    });
  });
});
