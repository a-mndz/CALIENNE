import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ProviderStatusBar from './ProviderStatusBar';

describe('ProviderStatusBar', () => {
  const providers = [
    { name: 'Groq', status: 'online' },
    { name: 'OpenRouter', status: 'offline' },
    { name: 'Local Fallback', status: 'unknown' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should display execution mode', () => {
    render(
      <ProviderStatusBar
        providers={providers}
        executionMode="Multi-Agent"
        onToggleTelemetry={vi.fn()}
        onToggleSidebar={vi.fn()}
      />
    );

    expect(screen.getAllByText('Multi-Agent').length).toBeGreaterThan(0);
  });

  it('should display provider indicators with tooltips', () => {
    render(
      <ProviderStatusBar
        providers={providers}
        executionMode="Fallback"
        onToggleTelemetry={vi.fn()}
        onToggleSidebar={vi.fn()}
      />
    );

    expect(screen.getByTitle('Groq: Online')).toBeInTheDocument();
    expect(screen.getByTitle('OpenRouter: Offline')).toBeInTheDocument();
    expect(screen.getByTitle('Local Fallback: Unknown')).toBeInTheDocument();
  });

  it('should call toggle handlers', () => {
    const onToggleTelemetry = vi.fn();
    const onToggleSidebar = vi.fn();

    render(
      <ProviderStatusBar
        providers={providers}
        executionMode="Multi-Agent"
        onToggleTelemetry={onToggleTelemetry}
        onToggleSidebar={onToggleSidebar}
      />
    );

    fireEvent.click(screen.getByLabelText('Open telemetry drawer'));
    fireEvent.click(screen.getByLabelText('Open sidebar'));

    expect(onToggleTelemetry).toHaveBeenCalledTimes(1);
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
  });
});
