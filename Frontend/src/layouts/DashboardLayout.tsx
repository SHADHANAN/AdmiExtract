import React, { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/Sidebar'
import { Navbar } from '../components/Navbar'

export const DashboardLayout: React.FC = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  return (
    <div className="relative min-h-screen bg-background text-foreground flex overflow-x-hidden selection:bg-emerald-200 selection:text-emerald-950 dark:selection:bg-emerald-800/60 dark:selection:text-emerald-200">
      <Sidebar
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />
      <div className="flex flex-col min-h-screen w-full lg:pl-64 transition-all duration-200">
        <Navbar onToggleMobileMenu={() => setIsMobileMenuOpen((prev) => !prev)} />
        <main className="flex-1 p-4 sm:p-6 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
