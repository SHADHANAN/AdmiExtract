import React from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/Sidebar'
import { Navbar } from '../components/Navbar'

export const DashboardLayout: React.FC = () => {
  return (
    <div className="relative min-h-screen bg-background text-foreground flex overflow-x-hidden selection:bg-indigo-500/30 selection:text-white">
      {/* Subtle ambient lighting orbs */}
      <div className="pointer-events-none fixed -top-40 -left-40 h-[500px] w-[500px] rounded-full bg-indigo-600/10 blur-[140px]" />
      <div className="pointer-events-none fixed top-1/3 -right-40 h-[450px] w-[450px] rounded-full bg-purple-600/10 blur-[140px]" />
      <div className="pointer-events-none fixed -bottom-40 left-1/3 h-[500px] w-[500px] rounded-full bg-indigo-500/8 blur-[150px]" />

      <Sidebar />
      <div className="pl-64 flex flex-col min-h-screen w-full relative z-10">
        <Navbar />
        <main className="flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
