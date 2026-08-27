import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from './ui/Button'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo)
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 my-6 rounded-2xl border border-destructive/20 bg-destructive/5 text-destructive space-y-4 max-w-2xl mx-auto shadow-sm">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-6 w-6 text-destructive shrink-0" />
            <h2 className="text-lg font-bold text-foreground m-0">
              {this.props.fallbackTitle || 'Something went wrong rendering this view'}
            </h2>
          </div>
          <p className="text-xs text-muted-foreground font-mono bg-background/60 p-3 rounded-lg border border-border overflow-x-auto">
            {this.state.error?.message || 'An unexpected runtime error occurred.'}
          </p>
          <div className="flex items-center gap-3 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={this.handleReset}
              className="cursor-pointer gap-2 border-destructive/30 text-destructive hover:bg-destructive/10"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Try Again
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => (window.location.href = '/batches')}
              className="cursor-pointer text-xs"
            >
              Back to Batches
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
