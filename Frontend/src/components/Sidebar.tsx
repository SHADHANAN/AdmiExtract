import React from 'react'
import { NavLink } from 'react-router-dom'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import {
  LayoutDashboard,
  FolderOpen,
  Users,
  CheckSquare,
  Download,
  Settings,
  GraduationCap,
  LogOut,
  BarChart3,
<<<<<<< HEAD
  Sparkles,
=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
} from 'lucide-react'

export const Sidebar: React.FC = () => {
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
        { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { to: '/batches', label: 'Admission Batches', icon: FolderOpen },
        { to: '/students', label: 'Students', icon: Users },
        { to: '/verification', label: 'Verification', icon: CheckSquare },
        { to: '/export', label: 'Excel Export', icon: Download },
      ]

  return (
<<<<<<< HEAD
    <aside className="fixed inset-y-0 left-0 z-20 flex h-full w-64 flex-col border-r border-white/[0.08] bg-[#0F172A]/85 backdrop-blur-2xl shadow-[4px_0_24px_rgba(0,0,0,0.5)]">
      {/* Brand Header */}
      <div className="flex h-16 items-center border-b border-white/[0.08] px-5 gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-500 via-indigo-600 to-purple-600 text-white shadow-md shadow-indigo-500/25">
          <GraduationCap className="h-5 w-5" />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-bold tracking-tight text-white truncate">Smart Admissions</span>
          <span className="text-[10px] font-semibold text-indigo-400 uppercase tracking-wider flex items-center gap-1">
            <Sparkles className="h-2.5 w-2.5" /> AI Platform
          </span>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 space-y-1.5 px-3 py-5 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Main Navigation
        </div>
=======
    <aside className="fixed inset-y-0 left-0 z-20 flex h-full w-64 flex-col border-r border-border bg-card">
      <div className="flex h-16 items-center border-b border-border px-6 gap-2">
        <GraduationCap className="h-8 w-8 text-primary" />
        <span className="text-lg font-bold tracking-tight text-foreground">Smart Admissions</span>
      </div>

      <nav className="flex-1 space-y-1 px-4 py-6">
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        {links.map((link) => {
          const Icon = link.icon
          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
<<<<<<< HEAD
                `flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-xl transition-all duration-200 ${
                  isActive
                    ? 'bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-semibold shadow-lg shadow-indigo-500/20'
                    : 'text-slate-400 hover:text-white hover:bg-white/[0.05]'
                }`
              }
            >
              <Icon className="h-4.5 w-4.5 flex-shrink-0" />
              <span className="truncate">{link.label}</span>
=======
                `flex items-center gap-3 px-4 py-2.5 text-sm font-medium rounded-lg transition-colors ${
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-xs'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                }`
              }
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              {link.label}
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
            </NavLink>
          )
        })}
      </nav>

<<<<<<< HEAD
      {/* Footer / User Profile & Logout */}
      <div className="border-t border-white/[0.08] p-3 bg-[#050816]/40 space-y-2">
        <div className="px-3 py-2.5 rounded-xl bg-[#111827]/80 border border-white/[0.08] shadow-inner">
          <div className="text-xs font-semibold text-white truncate">
            {user?.name || user?.username || 'User'}
          </div>
          <div className="text-[10px] text-slate-400 capitalize truncate mt-0.5">
            {user?.role === 'super_admin' ? 'Super Admin' : user?.role === 'department_admin' ? `Dept Admin (${user.department_code || 'All'})` : user?.role || 'Staff'}
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-xs font-semibold text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-xl transition-all duration-150 cursor-pointer"
        >
          <LogOut className="h-4 w-4 flex-shrink-0" />
          <span>Sign Out</span>
=======
      <div className="border-t border-border p-4">
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-sm font-medium text-destructive hover:bg-destructive/10 rounded-lg transition-colors cursor-pointer"
        >
          <LogOut className="h-5 w-5 flex-shrink-0" />
          Logout
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        </button>
      </div>
    </aside>
  )
}
