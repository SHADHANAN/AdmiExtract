import { create } from 'zustand'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const STORAGE_KEY = 'admi_extract_theme'

interface ThemeState {
  theme: ThemeMode
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemeMode) => void
}

const getSystemPreference = (): ResolvedTheme => {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const getInitialTheme = (): ThemeMode => {
  if (typeof window === 'undefined') return 'system'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored as ThemeMode
  }
  return 'system'
}

const applyThemeToDOM = (theme: ThemeMode): ResolvedTheme => {
  if (typeof document === 'undefined') return 'light'
  const root = document.documentElement
  const isDark =
    theme === 'dark' || (theme === 'system' && getSystemPreference() === 'dark')

  if (isDark) {
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
  } else {
    root.classList.remove('dark')
    root.style.colorScheme = 'light'
  }

  return isDark ? 'dark' : 'light'
}

export const useThemeStore = create<ThemeState>((set, get) => {
  const initialTheme = getInitialTheme()
  const initialResolved = applyThemeToDOM(initialTheme)

  // Listen to OS theme changes if window is available
  if (typeof window !== 'undefined') {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => {
      if (get().theme === 'system') {
        const resolved = applyThemeToDOM('system')
        set({ resolvedTheme: resolved })
      }
    }

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleChange)
    } else {
      mediaQuery.addListener(handleChange)
    }
  }

  return {
    theme: initialTheme,
    resolvedTheme: initialResolved,
    setTheme: (theme: ThemeMode) => {
      try {
        localStorage.setItem(STORAGE_KEY, theme)
      } catch (e) {
        console.warn('Failed to save theme to localStorage', e)
      }
      const resolved = applyThemeToDOM(theme)
      set({ theme, resolvedTheme: resolved })
    },
  }
})
