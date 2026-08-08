import React, { useEffect, useState } from 'react'
import { userService } from '../services/user'
import { departmentService } from '../services/department'
import type { User, Department } from '../types'
import { useToastStore } from '../store/useToastStore'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Card, CardContent } from '../components/ui/Card'
import { Plus, UserCheck, UserX, Key, Trash2, Search, Building2 } from 'lucide-react'

export const Users: React.FC = () => {
  const [users, setUsers] = useState<User[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const { addToast } = useToastStore()

  // Modal states
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isResetModalOpen, setIsResetModalOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)

  // Form states
  const [formData, setFormData] = useState({
    username: '',
    name: '',
    email: '',
    password: '',
    department_code: '',
  })
  const [newPassword, setNewPassword] = useState('')

  const fetchUsers = async () => {
    try {
      setIsLoading(true)
      const [userList, deptList] = await Promise.all([
        userService.getAll(),
        departmentService.getAll(),
      ])
      setUsers(userList)
      setDepartments(deptList)
      if (deptList.length > 0 && !formData.department_code) {
        setFormData((prev) => ({ ...prev, department_code: deptList[0].name }))
      }
    } catch (err: any) {
      addToast(err?.message || 'Failed to load users', 'error')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
  }, [])

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.username || !formData.name || !formData.password) {
      addToast('Username, name, and password are required', 'error')
      return
    }

    try {
      await userService.create({
        username: formData.username,
        name: formData.name,
        email: formData.email || undefined,
        password: formData.password,
        role: 'department_admin',
        department_code: formData.department_code || undefined,
      })
      addToast('Department Admin user created successfully', 'success')
      setIsCreateModalOpen(false)
      setFormData({ username: '', name: '', email: '', password: '', department_code: departments[0]?.name || '' })
      fetchUsers()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to create user'
      addToast(msg, 'error')
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedUser || !newPassword) return

    try {
      await userService.resetPassword(selectedUser.id, newPassword)
      addToast(`Password reset successfully for ${selectedUser.username}`, 'success')
      setIsResetModalOpen(false)
      setSelectedUser(null)
      setNewPassword('')
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to reset password'
      addToast(msg, 'error')
    }
  }

  const handleToggleStatus = async (user: User) => {
    try {
      const updatedStatus = !user.is_active
      await userService.toggleStatus(user.id, updatedStatus)
      addToast(`User ${user.username} is now ${updatedStatus ? 'enabled' : 'disabled'}`, 'success')
      fetchUsers()
    } catch (err: any) {
      addToast('Failed to update user status', 'error')
    }
  }

  const handleDeleteUser = async (user: User) => {
    if (!window.confirm(`Are you sure you want to delete user "${user.username}"?`)) return
    try {
      await userService.delete(user.id)
      addToast(`User ${user.username} deleted`, 'success')
      fetchUsers()
    } catch (err: any) {
      addToast('Failed to delete user', 'error')
    }
  }

  const filteredUsers = users.filter(
    (u) =>
      u.username?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.department_code?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="User Management"
        description="Create and manage Department Admins, reset passwords, and toggle account access."
        action={
          <Button onClick={() => setIsCreateModalOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" />
            Create Department User
          </Button>
        }
      />

      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by username, name, or department..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="p-8 text-center text-muted-foreground">Loading users...</div>
          ) : filteredUsers.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No users found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border bg-secondary/50 text-xs font-semibold text-muted-foreground uppercase">
                  <tr>
                    <th className="px-4 py-3">User Details</th>
                    <th className="px-4 py-3">Role</th>
                    <th className="px-4 py-3">Department</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {filteredUsers.map((user) => (
                    <tr key={user.id} className="hover:bg-secondary/30 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-semibold text-foreground">{user.name}</div>
                        <div className="text-xs text-muted-foreground">@{user.username} {user.email && `• ${user.email}`}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            user.role === 'super_admin'
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'bg-secondary text-foreground'
                          }`}
                        >
                          {user.role === 'super_admin' ? 'Super Admin' : 'Department Admin'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {user.department_code ? (
                          <div className="flex items-center gap-1.5 text-foreground font-medium">
                            <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                            {user.department_code}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">All Departments</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 text-xs font-medium ${
                            user.is_active !== false ? 'text-emerald-600' : 'text-destructive'
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              user.is_active !== false ? 'bg-emerald-600' : 'bg-destructive'
                            }`}
                          />
                          {user.is_active !== false ? 'Active' : 'Disabled'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedUser(user)
                              setIsResetModalOpen(true)
                            }}
                            title="Reset Password"
                          >
                            <Key className="h-4 w-4 text-amber-500" />
                          </Button>
                          {user.role !== 'super_admin' && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleToggleStatus(user)}
                                title={user.is_active !== false ? 'Disable User' : 'Enable User'}
                              >
                                {user.is_active !== false ? (
                                  <UserX className="h-4 w-4 text-destructive" />
                                ) : (
                                  <UserCheck className="h-4 w-4 text-emerald-600" />
                                )}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDeleteUser(user)}
                                title="Delete User"
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create User Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl space-y-4">
            <h3 className="text-lg font-bold text-foreground">Create Department User</h3>
            <form onSubmit={handleCreateUser} className="space-y-4">
              <Input
                label="Username"
                placeholder="e.g. aiml"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                required
              />
              <Input
                label="Full Name"
                placeholder="e.g. AIML Department Admin"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
              <Input
                label="Email (Optional)"
                type="email"
                placeholder="aiml@institution.edu"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              />
              <Input
                label="Password"
                type="password"
                placeholder="••••••••"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                required
              />
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">Assigned Department</label>
                <select
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary"
                  value={formData.department_code}
                  onChange={(e) => setFormData({ ...formData, department_code: e.target.value })}
                >
                  {departments.map((dept) => (
                    <option key={dept.id} value={dept.name}>
                      {dept.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setIsCreateModalOpen(false)}
                >
                  Cancel
                </Button>
                <Button type="submit">Create User</Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reset Password Modal */}
      {isResetModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl space-y-4">
            <h3 className="text-lg font-bold text-foreground">
              Reset Password for {selectedUser.username}
            </h3>
            <form onSubmit={handleResetPassword} className="space-y-4">
              <Input
                label="New Password"
                type="password"
                placeholder="••••••••"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
              <div className="flex items-center justify-end gap-3 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setIsResetModalOpen(false)
                    setSelectedUser(null)
                  }}
                >
                  Cancel
                </Button>
                <Button type="submit">Reset Password</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
