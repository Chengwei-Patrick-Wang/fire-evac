import { Component } from 'react'
import type { ReactNode } from 'react'

export default class ErrorBoundary extends Component<{ label: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="pad errbox" role="alert">
        <p>
          {this.props.label} failed: {this.state.error.message}
        </p>
        <button onClick={() => location.reload()}>Reload</button>
      </div>
    )
  }
}
