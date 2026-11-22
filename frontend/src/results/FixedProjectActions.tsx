import { useIsMutating, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError, downloadFile } from '../api/client'
import { useMe } from '../api/hooks'
import type { Finding, Run } from '../api/types'
import type { Autofix } from '../components/autofix'
import { OverflowMenu, type MenuAction } from '../editor/CanvasHeader'
import { toast } from '../store/toast'

export function useOpenRecheck() {
  const nav = useNavigate()
  const location = useLocation()
  return (id: string) => {
    const params = new URLSearchParams(location.search)
    if (params.has('full')) nav(`/runs/${id}?${params}`)
    else {
      params.set('run', id)
      nav({ search: params.toString() })
    }
  }
}

interface BatchResult { run_id: string; skipped: string[] }

export function RunActions({ run, findings, full = false }: { run: Run; findings: Finding[]; full?: boolean }) {
  const { t } = useTranslation()
  const open = useOpenRecheck()
  const nav = useNavigate()
  const qc = useQueryClient()
  const role = useMe().data?.workspaces.find((w) => w.id === run.workspace_id)?.role
  const candidates = findings.filter((f) => f.autofix === 'deterministic' || f.autofix === 'llm')
  const [progress, setProgress] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const mutationKey = ['fix-all', run.id]
  const busy = useIsMutating({ mutationKey }) > 0
  const bulk = useMutation({
    mutationKey,
    mutationFn: async () => {
      const base = `/api/runs/${run.id}`
      const existing = await api<Autofix[]>(base + '/autofixes')
      const ids: string[] = []
      let firstError = ''
      let missingProvider = false
      for (const [index, finding] of candidates.entries()) {
        setProgress(index + 1)
        let patch = existing.find((p) => p.finding_id === finding.id && p.status === 'validated')
        if (!patch) {
          if (missingProvider && finding.autofix === 'llm') continue
          try {
            patch = await api<Autofix>(`${base}/findings/${finding.id}/autofix`, { method: 'POST', json: {} })
          } catch (e) {
            if (!(e instanceof ApiError)) throw e
            if (finding.autofix === 'llm' && ['ai_not_configured', 'provider_unavailable'].includes(e.code)) {
              missingProvider = true
            } else if (!['finding_not_reproduced', 'autofix_not_applicable'].includes(e.code)) {
              throw e
            }
            firstError ||= e.message
            continue
          }
        }
        if (patch.status === 'validated') ids.push(patch.id)
        else firstError ||= patch.reason ?? ''
      }
      if (!ids.length) throw new Error(firstError || t('results.noPatches'))
      const result = await api<BatchResult>(base + '/autofixes/recheck', { method: 'POST', json: { autofix_ids: ids } })
      return { id: result.run_id, skipped: candidates.length - ids.length + result.skipped.length }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['workflow', run.workflow_id] })
      void qc.invalidateQueries({ queryKey: ['workflows'] })
      void qc.invalidateQueries({ queryKey: ['runs'] })
    },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ['autofixes', run.id] }) },
  })
  const done = !['queued', 'running'].includes(run.status)
  const canFix = role === 'developer' || role === 'admin'
  const download = async (path: string, filename: string) => {
    setDownloading(true)
    try { await downloadFile(path, filename) }
    catch (e) { toast.error((e as Error).message) } finally { setDownloading(false) }
  }
  const items: MenuAction[] = ['report.md', 'submission.json', 'report.html'].map((filename) => ({
    key: filename, icon: 'download', label: filename, disabled: !done || downloading,
    onClick: () => void download(`/api/runs/${run.id}/export/${filename}`, filename),
  }))
  items.push(
    { key: 'compare', icon: 'split', label: t('results.compare'), disabled: !done,
      onClick: () => nav(`${run.workflow_id ? '/c/' + run.workflow_id : '/'}?panel=compare&head=${run.id}&run=${run.id}`) },
    { key: 'report', icon: 'external', label: t('results.fullReport'), disabled: full,
      onClick: () => nav(`/runs/${run.id}?full=1`) },
  )
  if (canFix) items.push(
    { key: 'fix', icon: 'wrench', label: t('results.fixAll'), disabled: busy || run.status !== 'success' || !candidates.length,
      onClick: () => bulk.mutate(undefined, {
        onSuccess: ({ id, skipped }) => {
          if (skipped) toast.info(t('results.skippedFixes', { n: skipped }))
          open(id)
        },
      }) },
    { key: 'archive', icon: 'download', label: t('results.fixedProject'), disabled: !run.has_fixed_project || downloading,
      title: t('results.zipHint'), onClick: () => void download(`/api/runs/${run.id}/fixed-project.zip`, `fixed-${run.id}.zip`) },
  )
  return <div>
    <OverflowMenu items={items} label={t('results.actions')} align={full ? 'right' : 'left'} />
    {busy && <p role="status" className="mt-1 text-xs text-muted">{t('results.fixProgress', { n: progress, total: candidates.length })}</p>}
    {bulk.isError && <p role="alert" className="mt-1 text-xs text-danger">{bulk.error.message}</p>}
  </div>
}
