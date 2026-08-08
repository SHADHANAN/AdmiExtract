import React from 'react'
import { useToastStore } from '../../store/useToastStore'

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToastStore()

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full">
      {toasts.map((toast) => {
        const bgColors = {
          success: 'bg-green-600 text-white border-green-700',
          error: 'bg-destructive text-destructive-foreground border-destructive/50',
          info: 'bg-primary text-primary-foreground border-ring',
        }

        return (
          <div
            key={toast.id}
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
            </button>
          </div>
        )
      })}
    </div>
  )
}
