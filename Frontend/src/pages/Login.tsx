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
  Eye,
  EyeOff,
} from 'lucide-react'
import { authService } from '../services/auth'

const loginSchema = z.object({
  username: z.string().min(1, { message: 'Username is required' }),
  password: z.string().min(1, { message: 'Password is required' }),
})

type LoginForm = z.infer<typeof loginSchema>

export const Login: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
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
    try {
      // 1. Perform login
      const loginRes = await authService.login(data.username, data.password)

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
      addToast(`Welcome back, ${userProfile.name || userProfile.username}!`, 'success')

      // 5. Navigate to dashboard
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
    <div className="min-h-screen w-full flex flex-col justify-center items-center p-4 sm:p-6 bg-background text-foreground relative overflow-hidden">
      {/* Subtle emerald radial glow background */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none flex items-center justify-center overflow-hidden"
      >
        <div className="w-[520px] sm:w-[640px] h-[520px] sm:h-[640px] rounded-full bg-emerald-500/[0.06] dark:bg-emerald-500/[0.08] blur-[110px] sm:blur-[140px] -translate-y-6" />
      </div>

      {/* Top right theme toggle */}
      <div className="absolute top-4 right-4 sm:top-6 sm:right-6 z-10">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-[440px] sm:max-w-[460px] relative z-10">
        {/* ADMIEXTRACT Logo, Application Name, and Subtitle */}
        <div className="flex flex-col items-center mb-7 sm:mb-8 text-center">
          <div className="flex h-12 w-12 sm:h-13 sm:w-13 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-emerald-700 text-white shadow-lg shadow-emerald-700/25 ring-1 ring-white/20 mb-3.5 transition-transform duration-200 hover:scale-[1.03]">
            <ShieldCheck className="h-6 w-6 sm:h-7 sm:w-7" />
          </div>
          <h1 className="text-2xl sm:text-[26px] font-extrabold tracking-tight text-foreground">
            ADMIEXTRACT
          </h1>
          <p className="text-xs sm:text-[13px] font-medium text-muted-foreground mt-1">
            Student Admission &amp; Verification Platform
          </p>
        </div>

        {/* Staff Login Card */}
        <div className="bg-card dark:bg-[#121e19] rounded-2xl border border-border/80 dark:border-emerald-950/80 shadow-xl shadow-black/5 dark:shadow-black/30 p-7 sm:p-9 backdrop-blur-xs">
          <div className="mb-6">
            <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground">
              Staff Login
            </h2>
            <p className="text-xs sm:text-[13px] text-muted-foreground mt-1">
              Enter your institutional credentials to access your account.
            </p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            {/* Username or Institutional ID Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground/90 block">
                Username or Institutional ID
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-muted-foreground/80">
                  <User className="h-4 w-4" />
                </div>
                <input
                  type="text"
                  autoComplete="username"
                  placeholder="Enter your username or ID"
                  className={`flex h-11 sm:h-11.5 w-full rounded-xl border border-input/90 dark:border-emerald-900/40 bg-card dark:bg-[#101b16] pl-10 pr-3.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 dark:focus:border-emerald-400 shadow-2xs ${
                    errors.username ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
                  }`}
                  {...register('username')}
                />
              </div>
              {errors.username && (
                <span className="text-xs text-destructive font-medium block mt-1">
                  {errors.username.message}
                </span>
              )}
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground/90 block">
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-muted-foreground/80">
                  <Lock className="h-4 w-4" />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className={`flex h-11 sm:h-11.5 w-full rounded-xl border border-input/90 dark:border-emerald-900/40 bg-card dark:bg-[#101b16] pl-10 pr-10 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 dark:focus:border-emerald-400 shadow-2xs ${
                    errors.password ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
                  }`}
                  {...register('password')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-muted-foreground/80 hover:text-foreground transition-colors focus:outline-none cursor-pointer"
                  tabIndex={-1}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              {errors.password && (
                <span className="text-xs text-destructive font-medium block mt-1">
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
                className="w-full justify-center text-sm font-semibold h-11 sm:h-11.5 rounded-xl gap-2 shadow-md shadow-emerald-700/15 hover:shadow-lg hover:shadow-emerald-700/25 transition-all duration-150 cursor-pointer"
              >
                <span>Sign In</span>
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
