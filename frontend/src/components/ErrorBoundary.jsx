import { Component } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    if (typeof console !== "undefined") console.error("Calienne ErrorBoundary:", error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="err-boundary">
          <AlertCircle size={28} />
          <div className="err-boundary-title">Signal lost</div>
          <div className="err-boundary-body">{String(this.state.error?.message || "Unknown fault")}</div>
          <button className="btn-primary" onClick={() => this.setState({ hasError: false, error: null })}>
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
