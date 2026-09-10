import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import { Button } from '../components/ui/Button'
import { GraduationCap, Sparkles, User, Lock, ArrowRight, Shield } from 'lucide-react'

import { authService } from '../services/auth'

const loginSchema = z.object({
  username: z.string().min(1, { message: 'Username is required' }),
  password: z.string().min(1, { message: 'Password is required' }),
})

type LoginForm = z.infer<typeof loginSchema>

export const Login: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false)
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
      
      // 2. Set token in store temporarily for Profile call interceptor
      useAuthStore.getState().login(loginRes.access_token, {
        id: '',
        name: '',
        username: data.username,
        role: 'department_admin',
      })

      // 3. Fetch authenticated user profile details
      const userProfile = await authService.getMe()
      
      // 4. Save credentials
      login(loginRes.access_token, userProfile)
      addToast(`Welcome back, ${userProfile.name}!`, 'success')
    } catch (err: any) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      const message = err?.response?.data?.detail || err?.message || 'Login failed. Invalid credentials.'
      addToast(message, 'error')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8 overflow-hidden">
      {/* Ambient background glow orbs */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-indigo-600/15 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-[450px] h-[450px] bg-purple-600/15 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute -bottom-20 left-1/4 w-[400px] h-[400px] bg-indigo-500/10 rounded-full blur-[150px] pointer-events-none" />

      <div className="relative w-full max-w-md z-10">
        {/* Brand Header */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-500 via-indigo-600 to-purple-600 text-white shadow-xl shadow-indigo-500/30 mb-4">
            <GraduationCap className="h-7 w-7" />
          </div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 text-xs font-semibold uppercase tracking-wider mb-2">
            <Sparkles className="h-3 w-3 text-indigo-400" />
            <span>AI Document Verification</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Smart Admissions
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-xs">
            Enter your credentials to manage cohorts and verify student applications.
          </p>
        </div>

        {/* Glassmorphism Card */}
        <div className="rounded-3xl border border-white/[0.08] bg-[#0F172A]/75 p-8 shadow-[0_8px_40px_rgba(0,0,0,0.6)] backdrop-blur-2xl">
          <div className="mb-6">
            <h2 className="text-lg font-bold text-white tracking-tight">Sign in to your account</h2>
            <p className="text-xs text-slate-400 mt-0.5">Authorized institutional personnel only</p>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {/* Username Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300 tracking-tight">
                Username
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <User className="h-4 w-4" />
                </div>
                <input
                  type="text"
                  placeholder="Enter your username"
                  className={`flex h-10.5 w-full rounded-xl border border-white/[0.08] bg-[#111827]/80 pl-10 pr-3.5 py-2 text-sm text-white placeholder:text-slate-500 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] ${
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
              <label className="text-xs font-semibold text-slate-300 tracking-tight">
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <Lock className="h-4 w-4" />
                </div>
                <input
                  type="password"
                  placeholder="••••••••"
                  className={`flex h-10.5 w-full rounded-xl border border-white/[0.08] bg-[#111827]/80 pl-10 pr-3.5 py-2 text-sm text-white placeholder:text-slate-500 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] ${
                    errors.password ? 'border-destructive focus:ring-destructive/20 focus:border-destructive' : ''
                  }`}
                  {...register('password')}
                />
              </div>
              {errors.password && (
                <span className="text-xs text-destructive font-medium block mt-1">
                  {errors.password.message}
                </span>
              )}
            </div>

            {/* Submit Button */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full mt-3 h-11 text-sm font-semibold justify-center shadow-lg shadow-indigo-500/25"
              isLoading={isLoading}
            >
              <span>Sign In to Dashboard</span>
              {!isLoading && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>

          {/* Security Badge */}
          <div className="mt-6 pt-5 border-t border-white/[0.08] flex items-center justify-center gap-1.5 text-xs text-slate-400">
            <Shield className="h-3.5 w-3.5 text-emerald-400" />
            <span>256-bit Encrypted Admission Portal</span>
          </div>
        </div>
      </div>
    </div>
  )
}

