import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuthStore } from '../store/useAuthStore'
import { useToastStore } from '../store/useToastStore'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import { GraduationCap } from 'lucide-react'

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
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center justify-center gap-2 mb-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg">
            <GraduationCap className="h-7 w-7" />
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight text-foreground">
            Smart Admissions
          </h2>
          <p className="text-sm text-muted-foreground">
            AI-Powered Document Verification System
          </p>
        </div>

        <Card className="border border-border bg-card shadow-lg backdrop-blur-xs">
          <CardHeader>
            <CardTitle>Sign in to your account</CardTitle>
            <CardDescription>
              Enter your credentials to access your dashboard
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <Input
                label="Username"
                type="text"
                placeholder="Enter your username"
                error={errors.username?.message}
                {...register('username')}
              />

              <Input
                label="Password"
                type="password"
                placeholder="••••••••"
                error={errors.password?.message}
                {...register('password')}
              />

              <Button
                type="submit"
                variant="primary"
                className="w-full mt-2"
                isLoading={isLoading}
              >
                Sign In
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

