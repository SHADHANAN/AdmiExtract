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
          <label className="text-xs sm:text-sm font-semibold text-foreground tracking-tight">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={`flex h-11 w-full rounded-xl border border-input dark:border-[#22382c] bg-card dark:bg-[#16251f] px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/60 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary hover:border-border dark:hover:border-[#2f4d3c] disabled:cursor-not-allowed disabled:opacity-60 shadow-2xs ${
            error ? 'border-destructive dark:border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
          } ${className}`}
          {...props}
        />
        {error && (
          <span className="text-xs text-destructive font-medium mt-0.5">{error}</span>
        )}
        {!error && helperText && (
          <span className="text-xs text-muted-foreground mt-0.5 leading-normal">{helperText}</span>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
