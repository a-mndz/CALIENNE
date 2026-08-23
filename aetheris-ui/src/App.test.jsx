import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import App from './App';
import { useChatStore } from './store/useChatStore';
import { fetchProviderStatus } from './api/client';

// Mock API client
vi.mock('./api/client', () => ({
  fetchProviderStatus: vi.fn(),
  setConnectionLostCallback: vi.fn(),
}));

// Mock child components to isolate App logic
vi.mock('./components/Sidebar', () => ({
  default: ({ conversations, activeId, onSelect, onNew, onDelete, open, onClose }) => (
    <div data-testid="sidebar" data-open={open}>
      <button onClick={onNew}>New Conversation</button>
      <button onClick={() => onSelect('test-id')}>Select Conversation</button>
      <button onClick={() => onDelete('test-id')}>Delete Conversation</button>
      <button onClick={onClose}>Close Sidebar</button>
    </div>
  ),
}));

vi.mock('./components/ChatWindow', () => ({
  default: ({ messages, currentStage, agentStates, partialData, onSuggestion }) => (
    <div data-testid="chat-window">
      <div>Messages: {messages.length}</div>
      <div>Stage: {currentStage}</div>
      <button onClick={() => onSuggestion('test')}>Suggestion</button>
    </div>
  ),
}));

vi.mock('./components/InputBox', () => ({
  default: ({ onSend, disabled }) => (
    <div data-testid="input-box">
      <button onClick={() => onSend('test')} disabled={disabled}>
        Send
      </button>
    </div>
  ),
}));

vi.mock('./components/ProviderStatusBar', () => ({
  default: ({ providers, executionMode, onToggleTelemetry, onToggleSidebar }) => (
    <div data-testid="provider-status-bar">
      <div>Providers: {providers.length}</div>
      <div>Execution Mode: {executionMode}</div>
      <button onClick={onToggleTelemetry}>Toggle Telemetry</button>
      <button onClick={onToggleSidebar}>Toggle Sidebar</button>
    </div>
  ),
}));

vi.mock('./components/TelemetryDrawer', () => ({
  default: ({ open, onClose, telemetry }) => (
    <div data-testid="telemetry-drawer" data-open={open}>
      <button onClick={onClose}>Close Telemetry</button>
      <div>Telemetry: {telemetry.length}</div>
    </div>
  ),
}));

vi.mock('./hooks/useSendQuery', () => ({
  useSendQuery: () => ({
    send: vi.fn(),
    stage: 'idle',
    agentStates: {},
    partialData: null,
  }),
}));

describe('App Component', () => {
  let originalLocation;
  let storage;

  beforeEach(() => {
    // Save original location
    originalLocation = window.location;

    vi.clearAllMocks();

    storage = {};

    localStorage.getItem.mockImplementation((key) => (key in storage ? storage[key] : null));
    localStorage.setItem.mockImplementation((key, value) => {
      storage[key] = String(value);
    });
    localStorage.removeItem.mockImplementation((key) => {
      delete storage[key];
    });
    localStorage.clear.mockImplementation(() => {
      storage = {};
    });

    // Reset localStorage before each test
    localStorage.clear();
    
    // Reset Zustand store
    useChatStore.setState({
      conversations: {
        'test-id': {
          id: 'test-id',
          title: 'Test Conversation',
          createdAt: Date.now(),
          messages: [],
        },
      },
      activeId: 'test-id',
      telemetry: [],
      providerHealth: [],
    });

    // Mock fetchProviderStatus to return successful response
    fetchProviderStatus.mockResolvedValue({
      providers: [
        { name: 'Groq', status: 'online' },
        { name: 'OpenRouter', status: 'online' },
      ],
    });

    // Mock window.location
    delete window.location;
    window.location = { href: '', assign: vi.fn() };
  });

  afterEach(() => {
    vi.useRealTimers();
    // Restore original location
    window.location = originalLocation;
    vi.restoreAllMocks();
  });

  describe('Authentication Gate', () => {
    it('should redirect to login when no access token exists', async () => {
      // No token in localStorage
      localStorage.removeItem('access_token');

      render(<App />);

      // Wait for effect to run
      await waitFor(() => {
        expect(window.location.href).toBe('/login');
      });
    });

    it('should render app when access token exists', () => {
      localStorage.setItem('access_token', 'test-token');

      render(<App />);

      // Should not redirect
      expect(window.location.href).not.toBe('/login');
      
      // Should render main components
      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('chat-window')).toBeInTheDocument();
      expect(screen.getByTestId('input-box')).toBeInTheDocument();
      expect(screen.getByTestId('provider-status-bar')).toBeInTheDocument();
    });

    it('should return null while unauthenticated', () => {
      localStorage.removeItem('access_token');

      const { container } = render(<App />);

      // Should render nothing (null)
      expect(container.firstChild).toBeNull();
    });
  });

  describe('Layout Structure', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'test-token');
    });

    it('should render Sidebar + MainLayout structure', () => {
      render(<App />);

      expect(screen.getByTestId('sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('provider-status-bar')).toBeInTheDocument();
      expect(screen.getByTestId('chat-window')).toBeInTheDocument();
      expect(screen.getByTestId('input-box')).toBeInTheDocument();
    });

    it('should render TelemetryDrawer as conditional panel', () => {
      render(<App />);

      const drawer = screen.getByTestId('telemetry-drawer');
      expect(drawer).toBeInTheDocument();
      expect(drawer.getAttribute('data-open')).toBe('false');
    });

    it('should display active conversation messages in ChatWindow', () => {
      useChatStore.setState({
        conversations: {
          'test-id': {
            id: 'test-id',
            title: 'Test',
            createdAt: Date.now(),
            messages: [
              { id: 'm1', role: 'user', content: 'Hello' },
              { id: 'm2', role: 'assistant', status: 'done' },
            ],
          },
        },
        activeId: 'test-id',
      });

      render(<App />);

      expect(screen.getByText(/Messages: 2/)).toBeInTheDocument();
    });
  });

  describe('Provider Health Polling', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'test-token');
    });

    it('should poll provider status on mount', async () => {
      render(<App />);

      await waitFor(() => {
        expect(fetchProviderStatus).toHaveBeenCalledTimes(1);
      });
    });

    it('should poll provider status every 30 seconds', async () => {
      vi.useFakeTimers();

      render(<App />);

      await act(async () => {
        await Promise.resolve();
      });

      expect(fetchProviderStatus).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30000);
        await Promise.resolve();
      });

      expect(fetchProviderStatus).toHaveBeenCalledTimes(2);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30000);
        await Promise.resolve();
      });

      expect(fetchProviderStatus).toHaveBeenCalledTimes(3);
    });

    it('should update providerHealth state with fetched data', async () => {
      fetchProviderStatus.mockResolvedValue({
        providers: [
          { name: 'Groq', status: 'online' },
          { name: 'OpenRouter', status: 'offline' },
        ],
        executionMode: 'Single-Agent',
      });

      render(<App />);

      await waitFor(() => {
        const state = useChatStore.getState();
        expect(state.providerHealth).toEqual([
          { name: 'Groq', status: 'online' },
          { name: 'OpenRouter', status: 'offline' },
        ]);
      });

      expect(screen.getByText('Execution Mode: Single-Agent')).toBeInTheDocument();
    });

    it('should map backend mode field to execution mode label', async () => {
      fetchProviderStatus.mockResolvedValue({
        providers: [{ name: 'Groq', status: 'online' }],
        mode: 'FREE',
      });

      render(<App />);

      await waitFor(() => {
        expect(screen.getByText('Execution Mode: Fallback')).toBeInTheDocument();
      });
    });

    it('should show unknown status when provider health fetch fails', async () => {
      fetchProviderStatus.mockResolvedValue(null);

      render(<App />);

      await waitFor(() => {
        const state = useChatStore.getState();
        expect(state.providerHealth).toEqual([
          { name: 'Groq', status: 'unknown' },
          { name: 'OpenRouter', status: 'unknown' },
          { name: 'Local Fallback', status: 'unknown' },
        ]);
      });
    });

    it('should not poll when unauthenticated', async () => {
      localStorage.removeItem('access_token');

      render(<App />);

      // Wait a bit
      await new Promise(resolve => setTimeout(resolve, 100));

      // Should not have been called
      expect(fetchProviderStatus).not.toHaveBeenCalled();
    });

    it('should stop polling on unmount', async () => {
      vi.useFakeTimers();

      const { unmount } = render(<App />);

      await act(async () => {
        await Promise.resolve();
      });

      expect(fetchProviderStatus).toHaveBeenCalledTimes(1);

      unmount();

      fetchProviderStatus.mockClear();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30000);
        await Promise.resolve();
      });

      expect(fetchProviderStatus).not.toHaveBeenCalled();
    });
  });

  describe('Mobile Sidebar Toggle', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'test-token');
    });

    it('should initialize sidebar as closed', () => {
      render(<App />);

      const sidebar = screen.getByTestId('sidebar');
      expect(sidebar.getAttribute('data-open')).toBe('false');
    });

    it('should open sidebar when toggle button is clicked', () => {
      render(<App />);

      const toggleButton = screen.getByText('Toggle Sidebar');
      fireEvent.click(toggleButton);

      const sidebar = screen.getByTestId('sidebar');
      expect(sidebar.getAttribute('data-open')).toBe('true');
    });

    it('should close sidebar when close button is clicked', () => {
      render(<App />);

      // Open sidebar first
      const toggleButton = screen.getByText('Toggle Sidebar');
      fireEvent.click(toggleButton);

      // Close sidebar
      fireEvent.click(screen.getByText('Close Sidebar'));

      const sidebar = screen.getByTestId('sidebar');
      expect(sidebar.getAttribute('data-open')).toBe('false');
    });
  });

  describe('Telemetry Drawer Toggle', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'test-token');
    });

    it('should initialize telemetry drawer as closed', () => {
      render(<App />);

      const drawer = screen.getByTestId('telemetry-drawer');
      expect(drawer.getAttribute('data-open')).toBe('false');
    });

    it('should open telemetry drawer when toggle button is clicked', () => {
      render(<App />);

      fireEvent.click(screen.getByText('Toggle Telemetry'));

      const drawer = screen.getByTestId('telemetry-drawer');
      expect(drawer.getAttribute('data-open')).toBe('true');
    });

    it('should close telemetry drawer when close button is clicked', () => {
      render(<App />);

      // Open drawer first
      fireEvent.click(screen.getByText('Toggle Telemetry'));

      // Close drawer
      fireEvent.click(screen.getByText('Close Telemetry'));

      const drawer = screen.getByTestId('telemetry-drawer');
      expect(drawer.getAttribute('data-open')).toBe('false');
    });
  });

  describe('Integration', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'test-token');
    });

    it('should pass correct props to child components', () => {
      const { providerHealth, telemetry, conversations, activeId } = useChatStore.getState();

      render(<App />);

      // Verify ProviderStatusBar receives providers
      expect(screen.getByText(`Providers: ${providerHealth.length}`)).toBeInTheDocument();

      // Verify TelemetryDrawer receives telemetry
      expect(screen.getByText(`Telemetry: ${telemetry.length}`)).toBeInTheDocument();

      // Verify ChatWindow receives messages
      const activeConversation = conversations[activeId];
      expect(screen.getByText(`Messages: ${activeConversation.messages.length}`)).toBeInTheDocument();
    });

    it('should maintain consistent state across re-renders', async () => {
      const { rerender } = render(<App />);

      // Update provider health
      await waitFor(() => {
        const state = useChatStore.getState();
        expect(state.providerHealth.length).toBeGreaterThan(0);
      });

      // Re-render
      rerender(<App />);

      // State should persist
      const state = useChatStore.getState();
      expect(state.providerHealth.length).toBeGreaterThan(0);
    });
  });
});
