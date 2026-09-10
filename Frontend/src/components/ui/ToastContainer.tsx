import React from 'react'
import { useToastStore } from '../../store/useToastStore'
<<<<<<< HEAD
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToastStore()

  return (
<<<<<<< HEAD
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => {
        const bgColors = {
          success: 'bg-[#0F172A]/95 text-white border border-emerald-500/30 shadow-xl shadow-emerald-500/10 backdrop-blur-xl',
          error: 'bg-[#0F172A]/95 text-white border border-rose-500/30 shadow-xl shadow-rose-500/10 backdrop-blur-xl',
          info: 'bg-[#0F172A]/95 text-white border border-indigo-500/30 shadow-xl shadow-indigo-500/10 backdrop-blur-xl',
        }

        const icons = {
          success: <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />,
          error: <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />,
          info: <Info className="h-4 w-4 shrink-0 text-indigo-400" />,
=======
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full">
      {toasts.map((toast) => {
        const bgColors = {
          success: 'bg-green-600 text-white border-green-700',
          error: 'bg-destructive text-destructive-foreground border-destructive/50',
          info: 'bg-primary text-primary-foreground border-ring',
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        }

        return (
          <div
            key={toast.id}
<<<<<<< HEAD
            className={`pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 rounded-xl border shadow-lg transition-all duration-200 ${bgColors[toast.type]}`}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {icons[toast.type]}
              <span className="text-xs font-semibold leading-snug">{toast.message}</span>
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="p-1 rounded-lg hover:bg-white/[0.08] text-slate-400 hover:text-white transition-colors shrink-0 cursor-pointer"
              title="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
=======
            className={`flex items-center justify-between p-4 rounded-lg border shadow-md transition-all duration-300 transform translate-y-0 ${bgColors[toast.type]}`}
          >
            <span className="text-sm font-medium">{toast.message}</span>
            <button
              onClick={() => removeToast(toast.id)}
              className="ml-4 hover:opacity-75 transition-opacity text-current cursor-pointer"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M6 18L18 6M6 6l12 12" />
              </svg>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
            </button>
          </div>
        )
      })}
    </div>
  )
}
