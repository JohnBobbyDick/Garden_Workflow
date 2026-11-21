import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Route, Routes } from 'react-router-dom'
import { Toaster } from './components/domain'
import { Page } from './components/layout/AppShell'
import { RunRoute, WorkspaceIndex } from './workspace/Entry'
import { WorkspaceLayout } from './workspace/WorkspaceLayout'
import { EmptyState, Spinner } from './components/ui'
import { AuthPage } from './pages/AuthPage'

const Editor = lazy(() => import('./editor/CanvasPage'))

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
          <Route element={<WorkspaceLayout />}>
            <Route index element={<WorkspaceIndex />} />
            <Route path="c/:id" element={<Editor />} />
            <Route path="runs/:id" element={<RunRoute />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
      <Toaster />
    </>
  )
}
