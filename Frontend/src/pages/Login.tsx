import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import { Button } from '../components/ui/Button'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import type { User as AuthUser } from '../types'
import {
  ShieldCheck,
  User,
  Lock,
  ArrowRight,
  FileCheck2,
  Sparkles,
  Layers,
  FileSpreadsheet,
  CheckCircle2,
} from 'lucide-react'
import { authService } from '../services/auth'

const loginSchema = z.object({
  username: z.string().min(1, { message: 'Username is required' }),
  password: z.string().min(1, { message: 'Password is required' }),
})

type LoginForm = z.infer<typeof loginSchema>

export const Login: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false)
  const navigate = useNavigate()
  const { login } = useAuthStore()
  const { addToast } = useToastStore()

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      username: '',
      password: '',
    },
  })

  const onSubmit = async (data: LoginForm) => {
    setIsLoading(true)
    console.log('[Auth Diagnostics] login request started')
    try {
      // 1. Perform login
      const loginRes = await authService.login(data.username, data.password)
      console.log('[Auth Diagnostics] HTTP status: 200 OK')
      console.log('[Auth Diagnostics] response payload keys:', Object.keys(loginRes))

      const token = loginRes.access_token || loginRes.token || loginRes.accessToken
      if (!token) {
        throw new Error('No authentication token received from server.')
      }

      // 2. Set token in store temporarily for Profile call interceptor
      const fallbackUser: AuthUser = {
        id: '',
        name: data.username,
        username: data.username,
        role: 'department_admin',
      }
      useAuthStore.getState().login(token, fallbackUser)
      console.log('[Auth Diagnostics] token successfully stored')

      // 3. Fetch authenticated user profile details
      let userProfile: AuthUser = fallbackUser
      try {
        const fetchedProfile = await authService.getMe()
        if (fetchedProfile && fetchedProfile.id) {
          userProfile = fetchedProfile
        }
      } catch (meErr: any) {
        console.warn('[Auth Diagnostics] /auth/me profile fetch fallback:', meErr?.message)
      }

      // 4. Save credentials & update auth state
      login(token, userProfile)
      console.log('[Auth Diagnostics] auth state updated')

      addToast(`Welcome back, ${userProfile.name || userProfile.username}!`, 'success')

      // 5. Navigate to dashboard
      console.log('[Auth Diagnostics] navigation started')
      navigate('/dashboard', { replace: true })
    } catch (err: any) {
      console.error('[Auth Diagnostics] Login error:', err)
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      const message =
        err?.response?.data?.detail || err?.message || 'Login failed. Invalid credentials.'
      addToast(message, 'error')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen w-full flex bg-background text-foreground overflow-hidden">
      {/* LEFT PANEL: Institutional Branding & Overview (Visible on lg+) */}
      <div className="hidden lg:flex lg:w-1/2 bg-[#064e3b] text-white flex-col justify-between p-12 relative overflow-hidden">
        {/* Subtle geometric pattern overlay */}
        <div className="absolute inset-0 opacity-5 pointer-events-none">
          <svg className="w-full h-full" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        </div>

        {/* Ambient accent glow */}
        <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-emerald-500/20 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-80 h-80 rounded-full bg-lime-400/10 blur-3xl pointer-events-none" />

        {/* Brand Header */}
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-lime-300 border border-white/15 shadow-sm">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xl font-extrabold tracking-tight text-white block">
                ADMIEXTRACT
              </span>
              <span className="text-xs text-emerald-200/90 font-medium">
                Student Admission &amp; Verification Platform
              </span>
            </div>
          </div>
        </div>

        {/* Central Abstract Feature Showcase */}
        <div className="relative z-10 my-auto py-8 space-y-8 max-w-lg">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-700/80 border border-emerald-600 text-lime-300 text-xs font-semibold uppercase tracking-wider mb-4">
              <Sparkles className="h-3.5 w-3.5 text-lime-400" />
              <span>AI-Powered Extraction</span>
            </div>
            <h1 className="text-3xl xl:text-4xl font-extrabold tracking-tight text-white leading-tight">
              Streamlined Student Admissions &amp; Verification
            </h1>
            <p className="text-sm xl:text-base text-emerald-100/80 mt-3 leading-relaxed">
              Automate multi-document ingestion, cross-validate identity fields, and maintain seamless section isolation for every admission batch.
            </p>
          </div>

          {/* Key Feature Cards */}
          <div className="space-y-3.5">
            <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/[0.07] border border-white/10 backdrop-blur-xs">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-700 text-lime-300 shrink-0">
                <FileCheck2 className="h-4.5 w-4.5" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                  Automated OCR &amp; Extraction
                </h4>
                <p className="text-xs text-emerald-100/70 mt-0.5">
                  High-accuracy extraction across certificates, identity cards, and allotment orders.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/[0.07] border border-white/10 backdrop-blur-xs">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-700 text-lime-300 shrink-0">
                <Layers className="h-4.5 w-4.5" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                  Multi-Document Reconciliation
                </h4>
                <p className="text-xs text-emerald-100/70 mt-0.5">
                  Cross-document candidate validation with clear field-source provenance tracking.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/[0.07] border border-white/10 backdrop-blur-xs">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-700 text-lime-300 shrink-0">
                <FileSpreadsheet className="h-4.5 w-4.5" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                  Master Excel Integration
                </h4>
                <p className="text-xs text-emerald-100/70 mt-0.5">
                  Instant population of institutional admission spreadsheets with zero data loss.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer info */}
        <div className="relative z-10 pt-4 border-t border-white/10 flex items-center justify-between text-xs text-emerald-200/70">
          <span>Institutional Access Only</span>
          <span>Version 2.0</span>
        </div>
      </div>

      {/* RIGHT PANEL: Staff Login Form */}
      <div className="w-full lg:w-1/2 flex flex-col justify-center items-center p-6 sm:p-10 lg:p-14 bg-background">
        <div className="w-full max-w-md space-y-6">
          {/* Top bar with ThemeToggle */}
          <div className="flex items-center justify-between">
            {/* Mobile Header Brand (Visible only when left hero is hidden) */}
            <div className="lg:hidden flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <span className="text-lg font-extrabold tracking-tight text-foreground block">
                  ADMIEXTRACT
                </span>
                <span className="text-xs text-muted-foreground">
                  Student Admission &amp; Verification
                </span>
              </div>
            </div>
            <div className="hidden lg:block" />
            <ThemeToggle />
          </div>

          {/* Login Card */}
          <div className="bg-card rounded-2xl border border-border shadow-sm p-7 sm:p-9">
            <div className="mb-6">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20 text-[11px] font-semibold uppercase tracking-wider mb-2.5">
                Staff Portal
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-foreground">
                Staff Login
              </h2>
              <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                Enter your institutional credentials to access your admissions console.
              </p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4.5">
              {/* Username Input */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">
                  Username or Institutional ID
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-muted-foreground">
                    <User className="h-4 w-4" />
                  </div>
                  <input
                    type="text"
                    placeholder="Enter your username"
                    className={`flex h-10.5 w-full rounded-lg border border-input bg-card pl-10 pr-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-2xs ${
                      errors.username ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
                    }`}
                    {...register('username')}
                  />
                </div>
                {errors.username && (
                  <span className="text-xs text-destructive font-medium block mt-0.5">
                    {errors.username.message}
                  </span>
                )}
              </div>

              {/* Password Input */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-foreground">
                    Password
                  </label>
                </div>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-muted-foreground">
                    <Lock className="h-4 w-4" />
                  </div>
                  <input
                    type="password"
                    placeholder="••••••••"
                    className={`flex h-10.5 w-full rounded-lg border border-input bg-card pl-10 pr-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary shadow-2xs ${
                      errors.password ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
                    }`}
                    {...register('password')}
                  />
                </div>
                {errors.password && (
                  <span className="text-xs text-destructive font-medium block mt-0.5">
                    {errors.password.message}
                  </span>
                )}
              </div>

              {/* Sign In Button */}
              <div className="pt-2">
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  isLoading={isLoading}
                  className="w-full justify-center text-sm font-semibold h-11 rounded-lg gap-2"
                >
                  <span>Sign In to Platform</span>
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </form>

            <div className="mt-6 pt-5 border-t border-border flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
              <span>Protected by role-based institutional authentication</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
