import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary.jsx';

function Boom({ shouldThrow }) {
  if (shouldThrow) {
    throw new Error('simulated render crash');
  }
  return <div>healthy child</div>;
}

describe('ErrorBoundary (MED-024)', () => {
  it('renders children when no error is thrown', () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByText('healthy child')).toBeTruthy();
  });

  it('renders the fallback when a descendant throws', () => {
    // Silence React's noisy render-time logging so the test output stays clean.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText(/Something went wrong/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reload Calienne/i })).toBeTruthy();
    consoleError.mockRestore();
  });

  it('exposes the diagnostic detail in non-production', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom shouldThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText(/simulated render crash/)).toBeTruthy();
    consoleError.mockRestore();
  });
});
