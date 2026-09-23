import React from 'react'
import { useToastStore } from '../../store/useToastStore'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToastStore()

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => {
        const bgColors = {
          success: 'bg-card text-foreground border-emerald-500/30 shadow-lg shadow-emerald-500/5',
          error: 'bg-card text-foreground border-rose-500/30 shadow-lg shadow-rose-500/5',
          info: 'bg-card text-foreground border-sky-500/30 shadow-lg shadow-sky-500/5',
        }

        const icons = {
          success: <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />,
          error: <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />,
          info: <Info className="h-4 w-4 shrink-0 text-sky-600 dark:text-sky-400" />,
        }

        return (
          <div
            key={toast.id}
            className={`pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 rounded-xl border backdrop-blur-md transition-all duration-200 animate-in fade-in-0 slide-in-from-bottom-2 ${bgColors[toast.type]}`}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {icons[toast.type]}
              <span className="text-xs font-semibold leading-snug">{toast.message}</span>
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="p-1 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors shrink-0 cursor-pointer"
              title="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
