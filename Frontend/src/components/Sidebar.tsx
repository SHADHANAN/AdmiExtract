import React from 'react'
import { NavLink } from 'react-router-dom'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import {
  LayoutDashboard,
  FolderOpen,
  Users,
  Settings,
  ShieldCheck,
  LogOut,
  BarChart3,
  Sparkles,
  X,
} from 'lucide-react'

interface SidebarProps {
  isOpen?: boolean
  onClose?: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = false, onClose }) => {
  const { user, logout } = useAuthStore()
  const { addToast } = useToastStore()

  const handleLogout = () => {
    logout()
    addToast('Logged out successfully', 'success')
  }

  const isSuperAdmin = user?.role === 'super_admin'

  const links = isSuperAdmin
    ? [
        { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { to: '/departments', label: 'Departments', icon: FolderOpen },
        { to: '/users', label: 'Users', icon: Users },
        { to: '/overview', label: 'Overview', icon: BarChart3 },
        { to: '/settings', label: 'Settings', icon: Settings },
      ]
    : [
        { to: '/dashboard', label: 'Home', icon: LayoutDashboard },
        { to: '/batches', label: 'Admission Batches', icon: FolderOpen },
        { to: '/students', label: 'Students', icon: Users },
        { to: '/settings', label: 'Settings', icon: Settings },
      ]

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-xs lg:hidden transition-opacity"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Container — uses sidebar tokens for full theme-awareness */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-full w-64 flex-col border-r border-sidebar-border bg-sidebar shadow-sm transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        {/* Brand Header */}
        <div className="flex h-16 items-center justify-between border-b border-sidebar-border px-5">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-xs shrink-0">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-extrabold tracking-tight text-sidebar-foreground truncate">
                ADMIEXTRACT
              </span>
              <span className="text-[10px] font-semibold text-primary dark:text-emerald-400 uppercase tracking-wider flex items-center gap-1">
                <Sparkles className="h-2.5 w-2.5 text-accent-lime" />
                AI Admission Platform
              </span>
            </div>
          </div>

          {/* Close button for mobile */}
          {onClose && (
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-sidebar-foreground/50 hover:bg-sidebar-border/50 hover:text-sidebar-foreground lg:hidden cursor-pointer transition-colors"
              title="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
          )}
        </div>

        {/* Navigation Links */}
        <nav className="flex-1 space-y-1 px-3 py-4 overflow-y-auto">
          <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-sidebar-foreground/40">
            Navigation
          </div>
          {links.map((link) => {
            const Icon = link.icon
            return (
              <NavLink
                key={link.to}
                to={link.to}
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-2.5 text-sm font-medium rounded-lg transition-all duration-150 ${
                    isActive
                      ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                      : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-border/40'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <div className="flex items-center gap-3 min-w-0">
                      <Icon
                        className={`h-4.5 w-4.5 shrink-0 ${
                          isActive ? 'text-primary-foreground' : 'text-sidebar-foreground/50'
                        }`}
                      />
                      <span className="truncate">{link.label}</span>
                    </div>
                    {isActive && (
                      <span className="h-2 w-2 rounded-full bg-accent-lime shrink-0" />
                    )}
                  </>
                )}
              </NavLink>
            )
          })}
        </nav>

        {/* User Profile & Sign Out Footer */}
        <div className="border-t border-sidebar-border p-3 bg-sidebar-border/20 space-y-2">
          <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-sidebar border border-sidebar-border shadow-2xs">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-primary font-bold text-xs shrink-0">
              {(user?.name || user?.username || 'A').charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-bold text-sidebar-foreground truncate">
                {user?.name || user?.username || 'Staff User'}
              </div>
              <div className="text-[10px] text-sidebar-foreground/50 capitalize truncate">
                {user?.role === 'super_admin'
                  ? 'Super Admin'
                  : user?.role === 'department_admin'
                  ? `Dept Admin (${user.department_code || 'All'})`
                  : user?.role || 'Staff'}
              </div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-xs font-semibold text-sidebar-foreground/60 hover:text-rose-500 dark:hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors cursor-pointer"
          >
            <LogOut className="h-4 w-4 shrink-0" />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>
    </>
  )
}
