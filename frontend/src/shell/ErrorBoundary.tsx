import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/sdk";

/**
 * A page that crashes shows a message and a way out instead of a blank screen. `resetKey` (the URL) clears the error
 * when the person navigates elsewhere.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("Page crashed", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-md py-16 text-center">
        <p className="text-lg font-semibold">This page hit a problem</p>
        <p className="mt-2 text-sm text-muted">Nothing you entered has been lost on the server. Reload the page, or go back to the home screen.</p>
        <div className="mt-5 flex justify-center gap-2">
          <Button onClick={() => window.location.reload()}>Reload</Button>
          <Button variant="secondary" onClick={() => { window.location.href = "/"; }}>Home</Button>
        </div>
      </div>
    );
  }
}
