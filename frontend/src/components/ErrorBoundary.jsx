import { Component } from 'react'

export default class ErrorBoundary extends Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('ChronoCut UI crash:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-void p-6">
          <div className="max-w-lg rounded-2xl border border-red-500/30 bg-red-500/10 p-8 text-center">
            <h2 className="font-display text-3xl text-red-400">UI CRASHED</h2>
            <p className="mt-4 font-mono text-sm text-bone/70">
              {this.state.error?.message || 'Unknown error'}
            </p>
            <pre className="mt-4 overflow-auto rounded-lg bg-black/40 p-4 font-mono text-[10px] text-ash/70">
              {this.state.error?.stack}
            </pre>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-6 rounded-full border border-white/20 px-6 py-3 font-mono text-[11px] uppercase tracking-widest2 text-bone transition-colors hover:border-white/60"
            >
              Retry
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
