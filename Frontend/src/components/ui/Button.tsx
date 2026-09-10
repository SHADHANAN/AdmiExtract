import React from 'react'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost'
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
<<<<<<< HEAD
  const baseStyles = 'inline-flex items-center justify-center font-medium transition-all duration-200 select-none focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[#050816] disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed cursor-pointer'
  
  const variants = {
    primary: 'bg-gradient-to-r from-indigo-500 via-indigo-600 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-lg shadow-indigo-500/25 border border-indigo-400/20 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus:ring-indigo-500/30',
    secondary: 'bg-[#0F172A] text-slate-200 hover:bg-[#1E293B] border border-white/[0.08] hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus:ring-white/10',
    outline: 'border border-white/[0.12] bg-transparent text-slate-200 hover:bg-white/[0.06] hover:border-white/[0.2] hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus:ring-white/10',
    danger: 'bg-red-500/15 text-red-400 border border-red-500/25 hover:bg-red-500/25 shadow-xs shadow-red-500/10 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus:ring-red-500/30',
    ghost: 'bg-transparent text-slate-400 hover:text-white hover:bg-white/[0.05] focus:ring-white/10 active:scale-[0.98]',
  }
  
  const sizes = {
    sm: 'px-3 py-1.5 text-xs rounded-lg gap-1.5',
    md: 'px-4 py-2 text-sm rounded-xl gap-2',
    lg: 'px-5 py-2.5 text-base rounded-xl gap-2.5',
=======
  const baseStyles = 'inline-flex items-center justify-center font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none'
  
  const variants = {
    primary: 'bg-primary text-primary-foreground hover:opacity-90 focus:ring-primary',
    secondary: 'bg-secondary text-secondary-foreground hover:bg-opacity-95 focus:ring-secondary',
    outline: 'border border-border bg-transparent text-foreground hover:bg-secondary focus:ring-primary',
    danger: 'bg-destructive text-destructive-foreground hover:opacity-90 focus:ring-destructive',
    ghost: 'bg-transparent text-foreground hover:bg-secondary focus:ring-primary',
  }
  
  const sizes = {
    sm: 'px-3 py-1.5 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-5 py-2.5 text-base',
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
  }

  return (
    <button
      disabled={disabled || isLoading}
      className={`${baseStyles} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {isLoading && (
<<<<<<< HEAD
        <svg className="animate-spin -ml-0.5 mr-2 h-4 w-4 text-current" fill="none" viewBox="0 0 24 24">
=======
        <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-current" fill="none" viewBox="0 0 24 24">
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      )}
      {children}
    </button>
  )
}
