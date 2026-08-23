import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Sidebar from './Sidebar';

vi.mock('./TriadMark', () => ({
  default: () => <span data-testid="triad-mark" />,
}));

const conversations = {
  'conv-1': {
    id: 'conv-1',
    title: 'Renewable Energy Analysis',
    createdAt: Date.now() - 3600000,
    messages: [{ id: 'm1', role: 'user', content: 'Analyze renewable energy' }],
  },
  'conv-2': {
    id: 'conv-2',
    title: 'Quantum Computing',
    createdAt: Date.now() - 86400000,
    messages: [{ id: 'm2', role: 'user', content: 'Explain quantum computing' }],
  },
};

describe('Sidebar', () => {
  let storage;

  const onSelect = vi.fn();
  const onNew = vi.fn();
  const onDelete = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
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

    localStorage.setItem('user_email', 'user@example.com');
  });

  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('should render conversation list sorted by most recent first', () => {
    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    const titles = screen.getAllByText(/Renewable Energy Analysis|Quantum Computing/);
    expect(titles[0]).toHaveTextContent('Renewable Energy Analysis');
  });

  it('should filter conversations with debounced search', async () => {
    vi.useFakeTimers();

    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    fireEvent.change(screen.getByLabelText('Search conversations'), {
      target: { value: 'quantum' },
    });

    expect(screen.getByText('Renewable Energy Analysis')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(screen.queryByText('Renewable Energy Analysis')).not.toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === 'Quantum Computing')
    ).toBeInTheDocument();
  });

  it('should show no results message when search has no matches', async () => {
    vi.useFakeTimers();

    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    fireEvent.change(screen.getByLabelText('Search conversations'), {
      target: { value: 'nonexistent topic' },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(screen.getByText('No results')).toBeInTheDocument();
  });

  it('should clear search when clear button is clicked', async () => {
    vi.useFakeTimers();

    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    fireEvent.change(screen.getByLabelText('Search conversations'), {
      target: { value: 'quantum' },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    fireEvent.click(screen.getByLabelText('Clear search'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(screen.getByLabelText('Search conversations')).toHaveValue('');
    expect(screen.getByText('Renewable Energy Analysis')).toBeInTheDocument();

    vi.useRealTimers();
  });

  it('should require confirmation before deleting a conversation', () => {
    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getAllByLabelText(/Delete/)[0]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Delete'));
    expect(onDelete).toHaveBeenCalledWith('conv-1');
  });

  it('should cancel delete when cancel button is clicked', () => {
    render(
      <Sidebar
        conversations={conversations}
        activeId="conv-1"
        onSelect={onSelect}
        onNew={onNew}
        onDelete={onDelete}
        open={false}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getAllByLabelText(/Delete/)[0]);
    fireEvent.click(screen.getByText('Cancel'));

    expect(onDelete).not.toHaveBeenCalled();
  });
});
