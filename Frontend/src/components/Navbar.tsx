import React from 'react'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
<<<<<<< HEAD
import { LogOut, User as UserIcon, ShieldCheck } from 'lucide-react'
=======
import { LogOut, User as UserIcon } from 'lucide-react'
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4

export const Navbar: React.FC = () => {
  const { user, logout } = useAuthStore()
  const { addToast } = useToastStore()

  const handleLogout = () => {
    logout()
    addToast('Logged out successfully', 'success')
  }

<<<<<<< HEAD
  const roleLabel =
    user?.role === 'super_admin'
      ? 'Super Admin'
      : user?.role === 'department_admin'
      ? `Department Admin (${user.department_code || 'All'})`
      : user?.role || 'Staff'

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-white/[0.08] bg-[#0F172A]/75 backdrop-blur-xl px-6 shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
      <div className="flex items-center gap-3">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px] font-semibold shadow-xs shadow-emerald-500/10">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>System Online</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2.5 py-1.5 px-3 rounded-xl border border-white/[0.08] bg-[#111827]/80">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-400 font-bold text-xs">
            <UserIcon className="h-4 w-4" />
          </div>
          <div className="hidden sm:flex flex-col text-left">
            <span className="text-xs font-semibold text-white leading-tight">
              {user?.name || user?.username || 'Admin'}
            </span>
            <span className="text-[10px] text-slate-400 capitalize leading-tight">
              {roleLabel}
            </span>
=======
  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-border bg-card px-6 shadow-xs">
      <div className="flex items-center gap-4">
        {/* Logo or page context info placeholder */}
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-foreground">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-primary">
            <UserIcon className="h-4 w-4" />
          </div>
          <div className="hidden sm:block">
            <div className="text-xs text-muted-foreground capitalize mt-0.5">
              {user?.role === 'super_admin' ? 'Super Admin' : user?.role === 'department_admin' ? `Department Admin (${user.department_code || 'All'})` : user?.role}
            </div>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
          </div>
        </div>

        <button
          onClick={handleLogout}
<<<<<<< HEAD
          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.08] bg-[#111827]/80 text-slate-400 hover:text-red-400 hover:bg-red-500/10 hover:border-red-500/20 transition-all duration-200 cursor-pointer shadow-xs"
=======
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors cursor-pointer"
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
