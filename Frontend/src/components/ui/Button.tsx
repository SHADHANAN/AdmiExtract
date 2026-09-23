import React from 'react'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost' | 'accent'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  className = '',
  disabled,
  ...props
}) => {
  const baseStyles =
    'inline-flex items-center justify-center font-medium transition-all duration-150 select-none focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-background disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed cursor-pointer'

  const variants = {
    primary:
      'bg-primary hover:bg-primary-hover text-primary-foreground shadow-xs hover:shadow-sm border border-emerald-900/20 active:translate-y-0.5 focus:ring-primary/30',
    secondary:
      'bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border shadow-2xs active:translate-y-0.5 focus:ring-border',
    outline:
      'border border-border bg-card text-foreground hover:bg-secondary hover:border-border/80 shadow-2xs active:translate-y-0.5 focus:ring-border',
    danger:
      'bg-destructive/10 text-destructive border border-destructive/25 hover:bg-destructive/20 shadow-2xs active:translate-y-0.5 focus:ring-destructive/30',
    ghost:
      'bg-transparent text-muted-foreground hover:text-foreground hover:bg-secondary active:bg-secondary/60 focus:ring-border',
    accent:
      'bg-accent-lime hover:opacity-90 text-slate-950 font-semibold shadow-xs border border-lime-600/30 active:translate-y-0.5 focus:ring-accent-lime/40',
  }

  const sizes = {
    sm: 'px-3 py-1.5 text-xs rounded-lg gap-1.5',
    md: 'px-4 py-2 text-sm rounded-xl gap-2',
    lg: 'px-5 py-2.5 text-base rounded-xl gap-2.5',
  }

  return (
    <button
      disabled={disabled || isLoading}
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {isLoading && (
        <svg className="animate-spin -ml-0.5 mr-2 h-4 w-4 text-current" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      )}
      {children}
    </button>
  )
}
