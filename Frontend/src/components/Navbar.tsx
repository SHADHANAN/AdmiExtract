import React from 'react'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import { LogOut, User as UserIcon } from 'lucide-react'

export const Navbar: React.FC = () => {
  const { user, logout } = useAuthStore()
  const { addToast } = useToastStore()

  const handleLogout = () => {
    logout()
    addToast('Logged out successfully', 'success')
  }

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
          </div>
        </div>

        <button
          onClick={handleLogout}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors cursor-pointer"
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
