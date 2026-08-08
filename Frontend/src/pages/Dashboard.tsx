import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import { departmentService } from '../services/department'
import { userService } from '../services/user'
import { batchService } from '../services/batch'
import { studentSubmissionService } from '../services/studentSubmission'
import { useAuthStore } from '../store/useAuthStore'
import { useBatchStore } from '../store/useBatchStore'
import { Users, Building2, Link as LinkIcon, AlertCircle, CheckCircle, FolderOpen, CheckSquare } from 'lucide-react'

export const Dashboard: React.FC = () => {
  const { user } = useAuthStore()
  const isSuperAdmin = user?.role === 'super_admin'

  // 1. Super Admin Queries
  const { data: departments = [], isLoading: isDeptsLoading } = useQuery({
    queryKey: ['departments'],
    queryFn: departmentService.getAll,
    enabled: isSuperAdmin,
  })

  const { data: users = [], isLoading: isUsersLoading } = useQuery({
    queryKey: ['users'],
    queryFn: userService.getAll,
    enabled: isSuperAdmin,
  })

  // 2. Department Admin Queries
  const { data: batches = [], isLoading: isBatchesLoading } = useQuery({
    queryKey: ['batches'],
    queryFn: batchService.getAll,
    enabled: !isSuperAdmin,
  })

  const { data: submissions = [], isLoading: isSubmissionsLoading } = useQuery({
    queryKey: ['submissions'],
    queryFn: studentSubmissionService.getAllSubmissions,
  })

  // 3. Read link stats from state store
  const { uploadLinks } = useBatchStore()

  // Stats generation based on role
  let stats: any[] = []

  if (isSuperAdmin) {
    const studentsCount = submissions.length
    const totalUsersCount = users.length

    stats = [
      {
        title: 'Total System Users',
        value: totalUsersCount.toString(),
        isLoading: isUsersLoading,
        icon: Users,
        color: 'text-blue-500 bg-blue-500/10',
      },
      {
        title: 'Departments Registered',
        value: departments.length.toString(),
        isLoading: isDeptsLoading,
        icon: Building2,
        color: 'text-indigo-500 bg-indigo-500/10',
      },
      {
        title: 'Active Upload Portals',
        value: uploadLinks.filter((l) => l.isActive).length.toString(),
        isLoading: false,
        icon: LinkIcon,
        color: 'text-purple-500 bg-purple-500/10',
      },
      {
        title: 'Students Registered',
        value: studentsCount.toString(),
        isLoading: isUsersLoading,
        icon: CheckCircle,
        color: 'text-green-500 bg-green-500/10',
      },
    ]
  } else {
    // Department Admin Stats
    const totalStudents = submissions.length
    const pendingVerification = submissions.filter(
      (s) => s.status === 'Verification Pending' || s.status === 'Submitted' || s.status === 'AI Processing'
    ).length
    const verifiedStudents = submissions.filter((s) => s.status === 'Verified').length

    stats = [
      {
        title: 'Admission Batches',
        value: batches.length.toString(),
        isLoading: isBatchesLoading,
        icon: FolderOpen,
        color: 'text-blue-500 bg-blue-500/10',
      },
      {
        title: 'Registered Students',
        value: totalStudents.toString(),
        isLoading: isSubmissionsLoading,
        icon: Users,
        color: 'text-indigo-500 bg-indigo-500/10',
      },
      {
        title: 'Pending Verification',
        value: pendingVerification.toString(),
        isLoading: isSubmissionsLoading,
        icon: AlertCircle,
        color: 'text-amber-500 bg-amber-500/10',
      },
      {
        title: 'Verified Candidates',
        value: verifiedStudents.toString(),
        isLoading: isSubmissionsLoading,
        icon: CheckSquare,
        color: 'text-green-500 bg-green-500/10',
      },
    ]
  }

  const recentActivity = [
    { id: 1, action: 'Document Uploaded', target: 'Alice Smith (Computer Science)', time: '5 minutes ago', status: 'pending' },
    { id: 2, action: 'Verification Approved', target: 'Bob Johnson (Business Management)', time: '20 minutes ago', status: 'approved' },
    { id: 3, action: 'New Link Generated', target: 'USA Fall 2027 intake', time: '1 hour ago', status: 'info' },
    { id: 4, action: 'Document Uploaded', target: 'Clara Oswald (Civil Engineering)', time: '2 hours ago', status: 'pending' },
    { id: 5, action: 'Verification Rejected', target: 'David Tennant (Medicine - Missing transcript)', time: '3 hours ago', status: 'rejected' },
  ]

  return (
    <div className="space-y-8">
      <PageHeader
        title="Admission Overview"
        description="Monitor student document uploads, extraction tasks, and verification statuses."
      />

      {/* Stats Grid with loading skeletons */}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, idx) => {
          const Icon = stat.icon
          return (
            <Card key={idx} className="transition-all hover:translate-y-[-2px] hover:shadow-md">
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <span className="text-sm font-medium text-muted-foreground">{stat.title}</span>
                <div className={`p-2 rounded-lg ${stat.color}`}>
                  <Icon className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                {stat.isLoading ? (
                  /* Loading Skeleton */
                  <div className="h-8 w-16 bg-muted animate-pulse rounded mt-1" />
                ) : (
                  <div className="text-2xl font-bold tracking-tight text-foreground mt-1">
                    {stat.value}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Main Sections */}
      <div className="grid gap-6 md:grid-cols-3">
        {/* Recent Activity Table/List */}
        <Card className="md:col-span-2 shadow-sm">
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>Latest events and submissions across all links</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flow-root">
              <ul className="-my-5 divide-y divide-border">
                {recentActivity.map((activity) => (
                  <li key={activity.id} className="py-4">
                    <div className="flex items-center space-x-4">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-foreground truncate">
                          {activity.action}
                        </p>
                        <p className="text-xs text-muted-foreground truncate">
                          {activity.target}
                        </p>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className="text-xs text-muted-foreground">
                          {activity.time}
                        </span>
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-semibold uppercase tracking-wider ${
                            activity.status === 'approved'
                              ? 'bg-green-100 text-green-800'
                              : activity.status === 'rejected'
                              ? 'bg-red-100 text-red-800'
                              : activity.status === 'pending'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-blue-100 text-blue-800'
                          }`}
                        >
                          {activity.status}
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>

        {/* AI System Status */}
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>System Performance</CardTitle>
            <CardDescription>Document AI extraction stats</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <div className="flex items-center justify-between text-sm font-medium mb-1">
                <span className="text-muted-foreground">OCR Accuracy</span>
                <span className="text-foreground">98.4%</span>
              </div>
              <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                <div className="bg-green-500 h-full rounded-full" style={{ width: '98.4%' }} />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between text-sm font-medium mb-1">
                <span className="text-muted-foreground">Field Classification</span>
                <span className="text-foreground">96.2%</span>
              </div>
              <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                <div className="bg-primary h-full rounded-full" style={{ width: '96.2%' }} />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between text-sm font-medium mb-1">
                <span className="text-muted-foreground">Verification Rate</span>
                <span className="text-foreground">87.5%</span>
              </div>
              <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                <div className="bg-purple-500 h-full rounded-full" style={{ width: '87.5%' }} />
              </div>
            </div>

            <div className="pt-4 border-t border-border mt-4 flex gap-3 text-xs text-muted-foreground leading-relaxed">
              <AlertCircle className="h-5 w-5 text-indigo-500 shrink-0 mt-0.5" />
              <span>AI model auto-retraining is active. Real-time extraction confidence scores are evaluated against validation thresholds.</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
