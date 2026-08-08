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
    <aside className="fixed inset-y-0 left-0 z-20 flex h-full w-64 flex-col border-r border-border bg-card">
      <div className="flex h-16 items-center border-b border-border px-6 gap-2">
        <GraduationCap className="h-8 w-8 text-primary" />
        <span className="text-lg font-bold tracking-tight text-foreground">Smart Admissions</span>
      </div>

      <nav className="flex-1 space-y-1 px-4 py-6">
        {links.map((link) => {
          const Icon = link.icon
          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 text-sm font-medium rounded-lg transition-colors ${
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-xs'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                }`
              }
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              {link.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="border-t border-border p-4">
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-sm font-medium text-destructive hover:bg-destructive/10 rounded-lg transition-colors cursor-pointer"
        >
          <LogOut className="h-5 w-5 flex-shrink-0" />
          Logout
        </button>
      </div>
    </aside>
  )
}
