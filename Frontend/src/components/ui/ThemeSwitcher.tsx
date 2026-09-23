import React, { useState, useRef, useEffect } from 'react'
import { Sun, Moon, Laptop, Check } from 'lucide-react'
import { useThemeStore, type ThemeMode } from '../../store/useThemeStore'

interface ThemeSwitcherProps {
  className?: string
  variant?: 'dropdown' | 'segmented'
}

const THEME_OPTIONS: { mode: ThemeMode; label: string; icon: React.FC<{ className?: string }> }[] = [
  { mode: 'light', label: 'Light', icon: Sun },
  { mode: 'dark', label: 'Dark', icon: Moon },
  { mode: 'system', label: 'System', icon: Laptop },
]

export const ThemeSwitcher: React.FC<ThemeSwitcherProps> = ({
  className = '',
  variant = 'dropdown',
}) => {
  const { theme, resolvedTheme, setTheme } = useThemeStore()
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  // Segmented control variant (e.g., for settings, login or mobile headers)
  if (variant === 'segmented') {
    return (
      <div
        className={`inline-flex items-center p-1 rounded-xl border border-border bg-secondary/60 text-xs font-semibold ${className}`}
        role="radiogroup"
        aria-label="Select color theme"
      >
        {THEME_OPTIONS.map(({ mode, label, icon: Icon }) => {
          const isActive = theme === mode
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={isActive}
              onClick={() => setTheme(mode)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all cursor-pointer select-none text-xs ${
                isActive
                  ? 'bg-card text-foreground font-bold shadow-xs border border-border/80'
                  : 'text-muted-foreground hover:text-foreground hover:bg-card/40'
              }`}
            >
              <Icon className={`h-3.5 w-3.5 ${mode === 'light' ? 'text-amber-500' : mode === 'dark' ? 'text-indigo-400' : 'text-slate-400'}`} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>
    )
  }

  // Current active icon for dropdown button
  const CurrentIcon =
    theme === 'light'
      ? Sun
      : theme === 'dark'
      ? Moon
      : Laptop

  return (
    <div className={`relative inline-block text-left ${className}`} ref={menuRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={`Current theme: ${theme}. Click to change theme.`}
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-semibold text-foreground/85 hover:bg-secondary hover:text-foreground transition-all duration-150 cursor-pointer shadow-2xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title="Switch theme (Light, Dark, System)"
      >
        <CurrentIcon
          className={`h-4 w-4 ${
            resolvedTheme === 'dark' ? 'text-emerald-400' : 'text-amber-500'
          }`}
        />
        <span className="hidden md:inline capitalize">{theme}</span>
      </button>

      {isOpen && (
        <div
          role="menu"
          className="absolute right-0 mt-1.5 w-40 origin-top-right rounded-xl border border-border bg-popover p-1 shadow-lg backdrop-blur-md z-50 focus:outline-none animate-in fade-in-0 zoom-in-95 duration-100"
        >
          <div className="px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground border-b border-border/60 mb-1">
            Theme Mode
          </div>
          {THEME_OPTIONS.map(({ mode, label, icon: Icon }) => {
            const isActive = theme === mode
            return (
              <button
                key={mode}
                type="button"
                role="menuitem"
                onClick={() => {
                  setTheme(mode)
                  setIsOpen(false)
                }}
                className={`flex w-full items-center justify-between px-2.5 py-2 rounded-lg text-xs font-medium transition-colors cursor-pointer select-none ${
                  isActive
                    ? 'bg-primary/10 text-primary font-bold'
                    : 'text-foreground hover:bg-secondary'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon
                    className={`h-4 w-4 ${
                      mode === 'light'
                        ? 'text-amber-500'
                        : mode === 'dark'
                        ? 'text-emerald-500'
                        : 'text-slate-400'
                    }`}
                  />
                  <span>{label}</span>
                </div>
                {isActive && <Check className="h-3.5 w-3.5 stroke-[2.5]" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
