import { lazy, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useRun, useWorkflows } from '../api/hooks'
import { Button, ErrorState, Spinner } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { useWorkspaceUi } from '../store/workspace'

const RunDetailsPage = lazy(() => import('../pages/RunDetailsPage'))

const center = 'flex h-full items-center justify-center'

/** «/»: the last opened check (or the first one); with no checks — an empty canvas inviting a new check. */
export function WorkspaceIndex() {
  const { t } = useTranslation()
  const loc = useLocation()
  const wfs = useWorkflows()
  const last = useWorkspaceUi((s) => s.lastWorkflowId)
  const nav = useNavigate()
  const empty = !wfs.isLoading && !wfs.error && !(wfs.data ?? []).length
  // first visit: open «Новая проверка» right away
  useEffect(() => { if (empty && !loc.search.includes('new=1')) nav({ search: '?new=1' }, { replace: true }) }, [empty, loc.search, nav])
  if (wfs.isLoading) return <div className={center}><Spinner size={26} /></div>
  if (wfs.error) return <div className="p-6"><ErrorState error={wfs.error} onRetry={() => wfs.refetch()} /></div>
  const list = wfs.data ?? []
  const target = list.find((w) => w.id === last) ?? list[0]
  if (target) {
    // the auto-opened «Новая проверка» belongs to the empty state: never carry it into an existing check
    const p = new URLSearchParams(loc.search)
    p.delete('new')
    return <Navigate to={`/c/${target.id}${p.toString() ? `?${p}` : ''}`} replace />
  }
  return (
    <div className={`${center} canvas-empty bg-surface-2`}>
      <div className="max-w-md text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-card bg-soft text-primary"><Icon name="workflow" size={26} /></div>
        <h1 className="text-2xl font-bold">{t('ws.emptyTitle')}</h1>
        <p className="mt-2 text-muted">{t('ws.emptyHint')}</p>
        <Button className="mt-5" variant="primary" icon="plus" onClick={() => nav({ search: '?new=1' })}>{t('ws.newCheck')}</Button>
      </div>
    </div>
  )
}

/** «/runs/:id» (links from notifications, CI and report.html): the run inside its check, or the full report. */
export function RunRoute() {
  const { id } = useParams()
  const loc = useLocation()
  const run = useRun(id)
  if (run.isLoading) return <div className={center}><Spinner size={26} /></div>
  if (run.error) return <div className="p-6"><ErrorState error={run.error} onRetry={() => run.refetch()} /></div>
  if (run.data?.workflow_id && !new URLSearchParams(loc.search).has('full')) {
    const p = new URLSearchParams(loc.search)
    p.set('run', run.data.id)
    return <Navigate to={`/c/${run.data.workflow_id}?${p.toString()}`} replace />
  }
  return <div className="h-full overflow-y-auto"><RunDetailsPage /></div>
}
