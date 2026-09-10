import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { departmentService } from '../services/department'
import { userService } from '../services/user'
import { batchService } from '../services/batch'
import { studentSubmissionService } from '../services/studentSubmission'
import { useAuthStore } from '../store/useAuthStore'
import { useBatchStore } from '../store/useBatchStore'
import {
  Users,
  Building2,
  Link as LinkIcon,
  AlertCircle,
  CheckCircle2,
  FolderOpen,
  CheckSquare,
  FileText,
  ArrowUpRight,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'

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

  // Real Stats generation based on role (zero hardcoded values)
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
        color: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
      },
      {
        title: 'Departments Registered',
        value: departments.length.toString(),
        isLoading: isDeptsLoading,
        icon: Building2,
        color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20',
      },
      {
        title: 'Active Upload Portals',
        value: uploadLinks.filter((l) => l.isActive).length.toString(),
        isLoading: false,
        icon: LinkIcon,
        color: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
      },
      {
        title: 'Students Registered',
        value: studentsCount.toString(),
        isLoading: isSubmissionsLoading,
        icon: CheckCircle2,
        color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
      },
    ]
  } else {
    // Department Admin Real Stats
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
        color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20',
      },
      {
        title: 'Registered Students',
        value: totalStudents.toString(),
        isLoading: isSubmissionsLoading,
        icon: Users,
        color: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
      },
      {
        title: 'Pending Verification',
        value: pendingVerification.toString(),
        isLoading: isSubmissionsLoading,
        icon: AlertCircle,
        color: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
      },
      {
        title: 'Verified Candidates',
        value: verifiedStudents.toString(),
        isLoading: isSubmissionsLoading,
        icon: CheckSquare,
        color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
      },
    ]
  }

  // Real recent submissions (zero mock data)
  const recentSubmissions = [...submissions].slice(0, 6)

  // Real counts for breakdown summary
  const verifiedCount = submissions.filter((s) => s.status === 'Verified').length
  const pendingCount = submissions.filter(
    (s) => s.status === 'Verification Pending' || s.status === 'Submitted'
  ).length
  const processingCount = submissions.filter((s) => s.status === 'AI Processing').length
  const rejectedCount = submissions.filter((s) => s.status === 'Rejected').length
  const totalUploadedDocs = submissions.reduce(
    (acc, s) => acc + (s.documents ? s.documents.filter((d) => d.status === 'Uploaded').length : 0),
    0
  )

  return (
    <div className="space-y-8">
      <PageHeader
        title="Admission Overview"
        description="Monitor student document uploads, extraction tasks, and verification statuses in real time."
      />

      {/* Stats Grid */}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, idx) => {
          const Icon = stat.icon
          return (
            <Card
              key={idx}
              className="hover:-translate-y-0.5 hover:shadow-md transition-all duration-200 border-border/80"
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  {stat.title}
                </span>
                <div className={`p-2.5 rounded-xl border ${stat.color}`}>
                  <Icon className="h-4.5 w-4.5" />
                </div>
              </CardHeader>
              <CardContent>
                {stat.isLoading ? (
                  <div className="h-9 w-20 bg-muted animate-pulse rounded-lg mt-1" />
                ) : (
                  <div className="text-3xl font-extrabold tracking-tight text-foreground mt-1">
                    {stat.value}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Main Sections */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Real Recent Submissions List */}
        <Card className="lg:col-span-2 shadow-xs border-border/80">
          <CardHeader className="flex flex-row items-center justify-between pb-4 border-b border-border/60">
            <div>
              <CardTitle>Recent Student Submissions</CardTitle>
              <CardDescription>Latest candidate submissions received across active batches</CardDescription>
            </div>
            <Link
              to="/students"
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-primary-hover transition-colors"
            >
              <span>View All</span>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {isSubmissionsLoading ? (
              <div className="p-8 space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-muted/60 animate-pulse rounded-xl" />
                ))}
              </div>
            ) : recentSubmissions.length === 0 ? (
              <div className="p-8">
                <EmptyState
                  title="No submissions recorded yet"
                  description="When applicants upload their identity and academic documents through the admission link, their records will appear here automatically."
                  icon={<FileText className="h-7 w-7 text-muted-foreground/60" />}
                />
              </div>
            ) : (
              <div className="divide-y divide-white/[0.06]">
                {recentSubmissions.map((sub) => {
                  const statusStyles: Record<string, string> = {
                    Verified: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                    'Verification Pending': 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                    Submitted: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                    'AI Processing': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
                    Rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
                  }
                  const badgeClass = statusStyles[sub.status] || 'bg-slate-800 text-slate-300 border-slate-700'

                  return (
                    <div
                      key={sub.id}
                      className="flex items-center justify-between p-4 px-6 hover:bg-white/[0.03] transition-colors"
                    >
                      <div className="flex items-center gap-3.5 min-w-0">
                        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-400 font-bold text-xs shrink-0 border border-indigo-500/20">
                          {sub.name ? sub.name.charAt(0).toUpperCase() : 'S'}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-white truncate">{sub.name}</p>
                          <p className="text-xs text-slate-400 truncate font-mono">
                            Reg: {sub.registerNum || 'N/A'} {sub.className ? `• ${sub.className}` : ''}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 shrink-0">
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${badgeClass}`}
                        >
                          {sub.status}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Real Status Overview Widget (Zero Fake Analytics) */}
        <Card className="shadow-xs border-border/80 flex flex-col justify-between">
          <div>
            <CardHeader className="pb-4 border-b border-white/[0.08]">
              <CardTitle>Cohort Summary</CardTitle>
              <CardDescription>Live breakdown across active applicant submissions</CardDescription>
            </CardHeader>
            <CardContent className="pt-6 space-y-3.5">
              <div className="flex items-center justify-between p-3 rounded-xl bg-[#0F172A]/70 border border-white/[0.08]">
                <div className="flex items-center gap-2.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                  <span className="text-xs font-medium text-slate-300">Verified Candidates</span>
                </div>
                <span className="text-xs font-bold text-white font-mono">{verifiedCount}</span>
              </div>

              <div className="flex items-center justify-between p-3 rounded-xl bg-[#0F172A]/70 border border-white/[0.08]">
                <div className="flex items-center gap-2.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                  <span className="text-xs font-medium text-slate-300">Pending Review</span>
                </div>
                <span className="text-xs font-bold text-white font-mono">{pendingCount}</span>
              </div>

              <div className="flex items-center justify-between p-3 rounded-xl bg-[#0F172A]/70 border border-white/[0.08]">
                <div className="flex items-center gap-2.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-blue-400" />
                  <span className="text-xs font-medium text-slate-300">AI Processing</span>
                </div>
                <span className="text-xs font-bold text-white font-mono">{processingCount}</span>
              </div>

              {rejectedCount > 0 && (
                <div className="flex items-center justify-between p-3 rounded-xl bg-secondary/50 border border-border/60">
                  <div className="flex items-center gap-2.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-rose-500" />
                    <span className="text-xs font-semibold text-foreground">Needs Re-upload</span>
                  </div>
                  <span className="text-xs font-bold text-foreground font-mono">{rejectedCount}</span>
                </div>
              )}

              <div className="flex items-center justify-between p-3 rounded-xl bg-secondary/50 border border-border/60">
                <div className="flex items-center gap-2.5">
                  <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold text-foreground">Total Uploaded Docs</span>
                </div>
                <span className="text-xs font-bold text-foreground font-mono">{totalUploadedDocs}</span>
              </div>
            </CardContent>
          </div>

          <div className="p-6 pt-0 border-t border-border/60 mt-4">
            <div className="flex items-start gap-2.5 pt-4 text-xs text-muted-foreground leading-relaxed">
              <ShieldCheck className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span>Real-time records synchronized with MongoDB database and Excel template pipeline.</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
