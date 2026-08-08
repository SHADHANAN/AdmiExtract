import React from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/Sidebar'
import { Navbar } from '../components/Navbar'

export const DashboardLayout: React.FC = () => {
  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <div className="pl-64 flex flex-col min-h-screen">
        <Navbar />
        <main className="flex-1 p-8 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
