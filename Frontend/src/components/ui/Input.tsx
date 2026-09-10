import React from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', ...props }, ref) => {
    return (
      <div className="w-full flex flex-col gap-1.5">
        {label && (
<<<<<<< HEAD
          <label className="text-xs font-medium text-slate-300 tracking-tight">
=======
          <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
            {label}
          </label>
        )}
        <input
          ref={ref}
<<<<<<< HEAD
          className={`flex h-10 w-full rounded-xl border border-white/[0.08] bg-[#0F172A]/80 px-3.5 py-2 text-sm text-white placeholder:text-slate-500 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] disabled:cursor-not-allowed disabled:opacity-50 ${
            error ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
=======
          className={`flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
            error ? 'border-destructive focus-visible:ring-destructive' : ''
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
          } ${className}`}
          {...props}
        />
        {error && (
<<<<<<< HEAD
          <span className="text-xs text-destructive font-medium mt-0.5">{error}</span>
        )}
        {!error && helperText && (
          <span className="text-xs text-slate-400 mt-0.5">{helperText}</span>
=======
          <span className="text-xs text-destructive font-medium">{error}</span>
        )}
        {!error && helperText && (
          <span className="text-xs text-muted-foreground">{helperText}</span>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
