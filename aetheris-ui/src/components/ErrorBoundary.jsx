import React from 'react';

/**
 * Application-wide React error boundary (MED-024).
 *
 * Catches render-time exceptions in the descendant tree and renders a
 * minimal fallback so a single component crash does not unmount the
 * whole app.  Logs the underlying error to the console for diagnostics;
 * the user sees a recovery prompt with a reload button.
 */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Calienne UI error boundary caught:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReload = () => {
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  render() {
    const { error, errorInfo } = this.state;
    if (error) {
      return (
        <div
          role="alert"
          aria-live="assertive"
          className="error-boundary"
        >
          <h1>Something went wrong</h1>
          <p>
            The Calienne UI hit an unexpected error.  Your work is preserved;
            click below to reload and try again.
          </p>
          <button type="button" onClick={this.handleReload}>
            Reload Calienne
          </button>
          {process.env.NODE_ENV !== 'production' ? (
            <details style={{ marginTop: '1rem' }}>
              <summary>Diagnostic detail</summary>
              <pre>{error?.message}</pre>
              {errorInfo?.componentStack ? <pre>{errorInfo.componentStack}</pre> : null}
            </details>
          ) : null}
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
