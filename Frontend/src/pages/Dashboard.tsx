import React, { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { EmptyState } from '../components/ui/EmptyState'
import { departmentService } from '../services/department'
import { userService } from '../services/user'
import { studentSubmissionService } from '../services/studentSubmission'
import { useAuthStore } from '../store/useAuthStore'
import { useBatchStore } from '../store/useBatchStore'
import {
  Users,
  Building2,
  FolderOpen,
  ArrowRight,
  Layers,
  Calendar,
  Plus,
  ShieldCheck,
  FileSpreadsheet,
} from 'lucide-react'

export const Dashboard: React.FC = () => {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const isSuperAdmin = user?.role === 'super_admin'

  const { batches, fetchBatches } = useBatchStore()

  useEffect(() => {
    fetchBatches()
  }, [fetchBatches])

  // Queries
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

  const { data: submissions = [], isLoading: isSubmissionsLoading } = useQuery({
    queryKey: ['submissions'],
    queryFn: studentSubmissionService.getAllSubmissions,
  })

  // Live Statistics (100% backend data, zero hardcoded values)
  const totalStudents = submissions.length
  const totalBatches = batches.length
  const totalSections = batches.reduce((acc, b) => acc + (b.classes?.length || 0), 0)
  const verifiedStudents = submissions.filter((s) => s.status === 'Verified').length

  const statsCards = [
    {
      title: 'Total Students',
      value: totalStudents.toString(),
      isLoading: isSubmissionsLoading,
      icon: Users,
      badge: 'All Cohorts',
      description: `${verifiedStudents} verified submissions`,
    },
    {
      title: 'Admission Batches',
      value: totalBatches.toString(),
      isLoading: false,
      icon: FolderOpen,
      badge: 'Active Batches',
      description: 'Configured academic cohorts',
    },
    {
      title: 'Total Sections',
      value: totalSections.toString(),
      isLoading: false,
      icon: Layers,
      badge: 'Allocated',
      description: 'Class divisions across cohorts',
    },
  ]

  return (
    <div className="space-y-6 sm:space-y-8 animate-in fade-in duration-300">
      {/* SaaS Dashboard Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-border pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">
              Welcome back, {user?.name || user?.username || 'Admin'}
            </h1>
            <Badge variant="success" size="sm" dot>
              {user?.role === 'super_admin' ? 'Super Admin' : 'Admissions Portal'}
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
            Manage student admissions, document verification, and batch extractions from one unified dashboard.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap self-start md:self-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/students')}
            className="text-xs font-semibold"
          >
            <Users className="h-3.5 w-3.5 mr-1.5 text-muted-foreground" />
            View Students
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/data-extraction')}
            className="text-xs font-semibold"
          >
            <FileSpreadsheet className="h-3.5 w-3.5 mr-1.5 text-muted-foreground" />
            Data Extraction
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigate('/batches')}
            className="text-xs font-semibold"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Manage Batches
          </Button>
        </div>
      </div>

      {/* Core Admission Metrics Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {statsCards.map((stat, idx) => {
          const Icon = stat.icon
          return (
            <Card
              key={idx}
              className="border-border/80 hover:border-primary/40 hover:shadow-xs transition-all duration-200 relative overflow-hidden"
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                  {stat.title}
                </span>
                <div className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20 shrink-0">
                  <Icon className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent className="space-y-1">
                {stat.isLoading ? (
                  <div className="h-9 w-24 bg-secondary animate-pulse rounded-md my-1" />
                ) : (
                  <div className="flex items-baseline justify-between">
                    <span className="text-3xl font-extrabold tracking-tight text-foreground font-mono">
                      {stat.value}
                    </span>
                    <Badge variant="default" size="sm">
                      {stat.badge}
                    </Badge>
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground leading-normal">
                  {stat.description}
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Super Admin Institutional Overview (if applicable) */}
      {isSuperAdmin && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
              Institutional Administration
            </h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Card className="border-border/80 hover:border-border transition-colors">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Departments</span>
                <div className="p-2 rounded-lg bg-secondary text-foreground shrink-0 border border-border">
                  <Building2 className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-extrabold text-foreground font-mono">
                  {isDeptsLoading ? '...' : departments.length}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Registered academic departments</p>
              </CardContent>
            </Card>

            <Card className="border-border/80 hover:border-border transition-colors">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">System Users</span>
                <div className="p-2 rounded-lg bg-secondary text-foreground shrink-0 border border-border">
                  <Users className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-extrabold text-foreground font-mono">
                  {isUsersLoading ? '...' : users.length}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Staff and administrator accounts</p>
              </CardContent>
            </Card>

            <Card className="border-border/80 hover:border-border transition-colors">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Total Batches</span>
                <div className="p-2 rounded-lg bg-secondary text-foreground shrink-0 border border-border">
                  <FolderOpen className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-extrabold text-foreground font-mono">
                  {batches.length}
                </div>
                <p className="text-xs text-muted-foreground mt-1">Active admission cohorts configured</p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Admission Batches Section */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-foreground flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-primary" />
              <span>Admission Batches</span>
            </h2>
            <p className="text-xs text-muted-foreground">
              Active cohorts, section allocations, and candidate verification progress
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/batches')}
            className="text-xs self-start sm:self-auto"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Create Cohort
          </Button>
        </div>

        {batches.length === 0 ? (
          <EmptyState
            title="No Admission Batches"
            description="Create your first batch cohort to start managing student applications and document verification."
            icon={<FolderOpen className="h-7 w-7 text-primary" />}
            action={
              <Button variant="primary" size="md" onClick={() => navigate('/batches')}>
                <Plus className="h-4 w-4 mr-1.5" />
                Create Batch
              </Button>
            }
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {batches.map((batch) => {
              const batchClasses = batch.classes || []

              const batchSubs = submissions.filter(
                (s) => s.batchId === batch.id || s.batchName === batch.name
              )
              const batchStudentCount = batchSubs.length
              const batchVerifiedCount = batchSubs.filter((s) => s.status === 'Verified').length

              return (
                <Card
                  key={batch.id}
                  className="border-border/80 hover:border-primary/50 hover:shadow-xs transition-all duration-200 flex flex-col justify-between"
                >
                  <CardHeader className="pb-3 border-b border-border/60">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <Badge variant="success" size="sm" className="mb-1.5">
                          {batch.department || 'General'}
                        </Badge>
                        <CardTitle className="text-base font-bold text-foreground truncate">
                          {batch.name}
                        </CardTitle>
                      </div>
                      <Badge variant="default" size="sm" className="shrink-0 gap-1 font-mono">
                        <Calendar className="h-3 w-3 text-muted-foreground" />
                        {batch.academicYear || 'Cohort'}
                      </Badge>
                    </div>
                  </CardHeader>

                  <CardContent className="py-4 space-y-4 flex-1">
                    {/* Sections Pill Container */}
                    <div>
                      <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <Layers className="h-3.5 w-3.5 text-primary" />
                        <span>Sections</span>
                      </div>
                      {batchClasses.length === 0 ? (
                        <span className="text-xs text-muted-foreground/60 italic">No sections created yet</span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {batchClasses.map((cls) => (
                            <span
                              key={cls.id}
                              className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-secondary text-foreground border border-border"
                            >
                              Sec {cls.section || cls.class_name || 'A'}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Statistics Grid */}
                    <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border/60 text-center">
                      <div className="p-2 rounded-lg bg-secondary/40 border border-border/60">
                        <div className="text-[10px] font-bold text-muted-foreground uppercase">Students</div>
                        <div className="text-sm font-extrabold text-foreground font-mono mt-0.5">
                          {batchStudentCount}
                        </div>
                      </div>

                      <div className="p-2 rounded-lg bg-secondary/40 border border-border/60">
                        <div className="text-[10px] font-bold text-muted-foreground uppercase">Verified</div>
                        <div className="text-sm font-extrabold text-emerald-600 dark:text-emerald-400 font-mono mt-0.5">
                          {batchVerifiedCount}
                        </div>
                      </div>
                    </div>
                  </CardContent>

                  {/* Open Batch Action */}
                  <div className="p-4 pt-0">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => navigate(`/batches/${batch.id}`)}
                      className="w-full justify-center text-xs font-semibold gap-1.5 h-9"
                    >
                      <span>Open Batch</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
