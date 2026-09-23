import React from 'react'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import { LogOut, User as UserIcon, ShieldCheck, Menu } from 'lucide-react'
import { ThemeToggle } from './ui/ThemeToggle'

interface NavbarProps {
  onToggleMobileMenu?: () => void
}

export const Navbar: React.FC<NavbarProps> = ({ onToggleMobileMenu }) => {
  const { user, logout } = useAuthStore()
  const { addToast } = useToastStore()

  const handleLogout = () => {
    logout()
    addToast('Logged out successfully', 'success')
  }

  const roleLabel =
    user?.role === 'super_admin'
      ? 'Super Admin'
      : user?.role === 'department_admin'
      ? `Department Admin (${user.department_code || 'All'})`
      : user?.role || 'Staff'

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-border bg-card/90 backdrop-blur-md px-4 sm:px-6 shadow-2xs">
      <div className="flex items-center gap-3">
        {/* Mobile menu toggle */}
        <button
          onClick={onToggleMobileMenu}
          className="rounded-lg p-2 text-muted-foreground hover:bg-secondary hover:text-foreground lg:hidden cursor-pointer"
          title="Toggle Navigation Menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* System Online Badge */}
        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 text-[11px] font-semibold shadow-2xs">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
          <span className="hidden xs:inline">System Online</span>
        </div>
      </div>

      <div className="flex items-center gap-2.5">
        <ThemeToggle />

        <div className="flex items-center gap-2 py-1 px-2.5 rounded-lg border border-border bg-secondary/50">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-bold text-xs">
            <UserIcon className="h-3.5 w-3.5" />
          </div>
          <div className="hidden sm:flex flex-col text-left">
            <span className="text-xs font-semibold text-foreground leading-tight">
              {user?.name || user?.username || 'Admin'}
            </span>
            <span className="text-[10px] text-muted-foreground capitalize leading-tight">
              {roleLabel}
            </span>
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="inline-flex h-8.5 w-8.5 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-rose-600 hover:bg-rose-500/10 hover:border-rose-500/20 transition-colors cursor-pointer shadow-2xs"
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
