import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Route, Routes } from 'react-router-dom'
import { Toaster } from './components/domain'
import { AppShell, Page } from './components/layout/AppShell'
import { EmptyState, Spinner } from './components/ui'
import { AuthPage } from './pages/AuthPage'

const Dashboard = lazy(() => import('./pages/DashboardPage'))
const Projects = lazy(() => import('./pages/ProjectsPage'))
const Workflows = lazy(() => import('./pages/WorkflowsPage'))
const Editor = lazy(() => import('./editor/EditorPage'))
const Runs = lazy(() => import('./pages/RunsPage'))
const RunDetails = lazy(() => import('./pages/RunDetailsPage'))
const Compare = lazy(() => import('./pages/ComparePage'))
const Settings = lazy(() => import('./pages/SettingsPage'))
const Templates = lazy(() => import('./pages/TemplatesPage'))
const Integration = lazy(() => import('./pages/IntegrationPage'))

function NotFound() {
  const { t } = useTranslation()
  return <Page><EmptyState icon="search" title={t('notFound.title')} action={<Link className="text-primary" to="/">{t('notFound.home')}</Link>} /></Page>
}

const fallback = <div className="flex h-64 items-center justify-center"><Spinner size={26} /></div>

export default function App() {
  return (
    <>
      <Suspense fallback={fallback}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="projects" element={<Projects />} />
            <Route path="workflows" element={<Workflows />} />
            <Route path="workflows/:id" element={<Editor />} />
            <Route path="runs" element={<Runs />} />
            <Route path="runs/compare" element={<Compare />} />
            <Route path="runs/:id" element={<RunDetails />} />
            <Route path="settings" element={<Settings />} />
            <Route path="templates" element={<Templates />} />
            <Route path="integration" element={<Integration />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
      <Toaster />
    </>
  )
}
