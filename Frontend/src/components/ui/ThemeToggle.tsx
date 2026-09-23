import React from 'react'
import { ThemeSwitcher } from './ThemeSwitcher'

interface ThemeToggleProps {
  className?: string
  variant?: 'dropdown' | 'segmented'
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ className = '', variant = 'dropdown' }) => {
  return <ThemeSwitcher className={className} variant={variant} />
}
