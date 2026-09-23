import React from 'react'

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div
    className={`rounded-xl border border-border bg-card text-card-foreground shadow-xs transition-all ${className}`}
    {...props}
  />
)

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`flex flex-col space-y-1.5 p-5 md:p-6 ${className}`} {...props} />
)

export const CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({ className = '', ...props }) => (
  <h3 className={`text-base md:text-lg font-bold tracking-tight text-foreground leading-snug ${className}`} {...props} />
)

export const CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({ className = '', ...props }) => (
  <p className={`text-xs md:text-sm text-muted-foreground leading-relaxed ${className}`} {...props} />
)

export const CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`p-5 md:p-6 pt-0 ${className}`} {...props} />
)

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className = '', ...props }) => (
  <div className={`flex items-center p-5 md:p-6 pt-0 ${className}`} {...props} />
)
