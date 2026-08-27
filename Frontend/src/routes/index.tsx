import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ProtectedRoute } from './ProtectedRoute'
import { PublicRoute } from './PublicRoute'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { DashboardLayout } from '../layouts/DashboardLayout'
import { Login } from '../pages/Login'
import { Dashboard } from '../pages/Dashboard'
import { Departments } from '../pages/Departments'
import { Users } from '../pages/Users'
import { Overview } from '../pages/Overview'
import { Batches } from '../pages/Batches'
import { BatchDetails } from '../pages/BatchDetails'
import { ClassDetails } from '../pages/ClassDetails'
import { Students } from '../pages/Students'
import { VerificationPage } from '../pages/VerificationPage'
import { ExportPage } from '../pages/ExportPage'
import { Settings } from '../pages/Settings'
import { StudentUpload } from '../pages/StudentUpload'
import { StudentDocuments } from '../pages/StudentDocuments'

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Public Admin Login */}
      <Route
        path="/login"
        element={
          <PublicRoute>
            <Login />
          </PublicRoute>
        }
      />

      {/* ── Public Student Upload Portal ─────────────────────────────────
          /upload/:token           → Identity form (no auth)
          /upload/:batchId/documents/* → Document workspace (session-gated)
      ─────────────────────────────────────────────────────────────────── */}
      <Route path="/upload/:token" element={<StudentUpload />} />

      {/* Document upload workspace — session validated inside the component */}
      <Route path="/upload/:batchId/documents" element={<StudentDocuments />} />
      <Route path="/upload/:batchId/documents/processing" element={<StudentDocuments />} />
      <Route path="/upload/:batchId/documents/verify" element={<StudentDocuments />} />
      <Route path="/upload/:batchId/documents/success" element={<StudentDocuments />} />

      {/* Protected Admin Layout Routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="departments" element={<Departments />} />
        <Route path="users" element={<Users />} />
        <Route path="overview" element={<Overview />} />
        <Route path="batches" element={<Batches />} />
        <Route
          path="batches/:batchId"
          element={
            <ErrorBoundary fallbackTitle="Error loading Batch Dashboard">
              <BatchDetails />
            </ErrorBoundary>
          }
        />
        <Route
          path="classes/:classId"
          element={
            <ErrorBoundary fallbackTitle="Error loading Section Dashboard">
              <ClassDetails />
            </ErrorBoundary>
          }
        />
        <Route
          path="batches/:batchId/classes/:classId"
          element={
            <ErrorBoundary fallbackTitle="Error loading Section Dashboard">
              <ClassDetails />
            </ErrorBoundary>
          }
        />
        <Route path="students" element={<Students />} />
        <Route path="verification" element={<VerificationPage />} />
        <Route path="export" element={<ExportPage />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      {/* Wildcard Fallback */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
