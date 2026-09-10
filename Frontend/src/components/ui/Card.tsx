import React from 'react'

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
<<<<<<< HEAD
  <div
    className={`rounded-2xl border border-white/[0.08] bg-[#111827] text-white shadow-[0_4px_24px_rgba(0,0,0,0.35)] transition-all ${className}`}
    {...props}
  />
=======
  <div className={`rounded-xl border border-border bg-card text-card-foreground shadow-xs ${className}`} {...props} />
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
)

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`flex flex-col space-y-1.5 p-6 ${className}`} {...props} />
)

export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({ className = '', ...props }) => (
<<<<<<< HEAD
  <h3 className={`text-lg font-bold tracking-tight text-white leading-none ${className}`} {...props} />
)

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({ className = '', ...props }) => (
  <p className={`text-sm text-slate-400 leading-relaxed ${className}`} {...props} />
=======
  <h3 className={`text-lg font-semibold leading-none tracking-tight ${className}`} {...props} />
)

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({ className = '', ...props }) => (
  <p className={`text-sm text-muted-foreground ${className}`} {...props} />
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
)

export const CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`p-6 pt-0 ${className}`} {...props} />
)

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`flex items-center p-6 pt-0 ${className}`} {...props} />
)
