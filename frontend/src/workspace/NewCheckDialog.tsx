import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useInvalidate, useWs } from '../api/hooks'
import { Button, Input, Modal, Textarea } from '../components/ui'
import { Icon, type IconName } from '../components/ui/Icon'
import { UploadField } from '../editor/SchemaForm'
import { toast } from '../store/toast'
import { validateRepoInput } from './newCheck'

type SourceKind = 'link' | 'archive' | 'training'
type Start = { kind: 'starter'; id: string } | { kind: 'template'; id: string } | { kind: 'blank' } | { kind: 'prompt' }
interface Starter { id: string; title: string; description: string }

/** Event the canvas listens to when «Сменить источник» is applied to the open check. */
export const SET_SOURCE_EVENT = 'aisw:set-source'

export function NewCheckDialog({ mode, templateId, onClose }: { mode: 'create' | 'change-source'; templateId?: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  const ws = useWs()
  const nav = useNavigate()
  const invalidate = useInvalidate()
  const training = useQuery({ queryKey: ['demo-training'], staleTime: Infinity, queryFn: () => api<{ available: boolean; path: string | null }>('/api/demo/training') })
  const starters = useQuery({ queryKey: ['check-starters'], staleTime: Infinity, enabled: mode === 'create', queryFn: () => api<Starter[]>('/api/checks/starters') })
  const tpl = useQuery({ queryKey: ['template', templateId], enabled: !!templateId, queryFn: () => api<{ id: string; name: string; description: string }>(`/api/templates/${templateId}`) })
  const [kind, setKind] = useState<SourceKind>('link')
  const [url, setUrl] = useState('')
  const [ref, setRef] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [uploadId, setUploadId] = useState('')
  const [start, setStart] = useState<Start>(templateId ? { kind: 'template', id: templateId } : { kind: 'starter', id: 'full' })
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState<'open' | 'run' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const repo = validateRepoInput(url)
  const sourceReady = kind === 'link' ? repo.ok && confirm : kind === 'archive' ? !!uploadId : !!training.data?.available
  const startReady = mode === 'change-source' || start.kind !== 'prompt' || prompt.trim().length >= 3
  const repoHint = !url.trim() ? null : repo.ok ? null : t(`newCheck.err.${repo.reason}`)

  const sourceBody = async (): Promise<Record<string, unknown>> => {
    if (kind === 'link') {
      const a = await api<{ url: string; ref: string | null; subdir: string | null }>('/api/repos/attest', { method: 'POST', json: { workspace_id: ws, url, confirm } })
      return { mode: 'git_url', url: a.url, ref: ref.trim() || a.ref || undefined, subdir: a.subdir || undefined }
    }
    if (kind === 'archive') return { mode: 'upload', upload_id: uploadId }
    return { mode: 'training' }
  }

  const submit = async (andRun: boolean) => {
    setError(null)
    setBusy(andRun ? 'run' : 'open')
    try {
      const source = await sourceBody()
      if (mode === 'change-source') {
        const config = source.mode === 'git_url' ? { mode: 'git_url', git_url: source.url, ref: source.ref ?? '', ...(source.subdir ? { subdir: source.subdir } : {}) }
          : source.mode === 'upload' ? { mode: 'upload', upload_id: source.upload_id } : { mode: 'path', path: training.data?.path }
        window.dispatchEvent(new CustomEvent(SET_SOURCE_EVENT, { detail: config }))
        toast.success(t('newCheck.sourceChanged'))
        onClose()
        return
      }
      const startBody = start.kind === 'starter' ? { starter: start.id } : start.kind === 'template' ? { template_id: start.id }
        : start.kind === 'blank' ? { blank: true } : { prompt: prompt.trim() }
      const r = await api<{ workflow_id: string; needs_input: { node_id: string; field: string }[] }>('/api/checks',
        { method: 'POST', json: { workspace_id: ws, source, start: startBody } })
      await invalidate('workflows')
      if (r.needs_input.length) toast.info(t('newCheck.needsInput', { n: r.needs_input.length }))
      if (andRun && !r.needs_input.length) {
        const run = await api<{ id: string }>(`/api/workflows/${r.workflow_id}/run`, { method: 'POST', json: {} })
        nav(`/c/${r.workflow_id}?run=${run.id}`)
      } else {
        nav(`/c/${r.workflow_id}`)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally { setBusy(null) }
  }

  const sourceTabs: { id: SourceKind; icon: IconName; label: string; hidden?: boolean }[] = [
    { id: 'link', icon: 'folder-git', label: t('newCheck.link') },
    { id: 'archive', icon: 'upload', label: t('newCheck.archive') },
    { id: 'training', icon: 'sparkles', label: t('wf.modeTraining'), hidden: !training.data?.available },
  ]
  const card = (active: boolean) => clsx('flex w-full flex-col items-start rounded-card border p-3 text-left transition-colors',
    active ? 'border-primary bg-soft ring-2 ring-primary/20' : 'border-border bg-surface hover:border-primary/50')

  return (
    <Modal open onClose={onClose} wide title={mode === 'create' ? t('ws.newCheck') : t('canvas.changeSource')}
      footer={(
        <>
          {error && <p role="alert" className="mr-auto max-w-[60%] self-center text-[13px] text-danger">{error}</p>}
          {mode === 'create' ? (
            <>
              <Button disabled={!sourceReady || !startReady} loading={busy === 'open'} onClick={() => submit(false)}>{t('newCheck.createOpen')}</Button>
              <Button variant="primary" icon="play" disabled={!sourceReady || !startReady || start.kind === 'blank'} loading={busy === 'run'} onClick={() => submit(true)}>
                {t('newCheck.createRun')}</Button>
            </>
          ) : <Button variant="primary" disabled={!sourceReady} loading={busy === 'open'} onClick={() => submit(false)}>{t('newCheck.apply')}</Button>}
        </>
      )}>
      <section aria-labelledby="nc-what">
        <h3 id="nc-what" className="mb-2 text-base font-bold">1. {t('newCheck.what')}</h3>
        <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label={t('newCheck.what')}>
          {sourceTabs.filter((s) => !s.hidden).map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={kind === s.id} onClick={() => setKind(s.id)}
              className={clsx('inline-flex h-9 items-center gap-1.5 rounded-chip px-3 text-[13px] font-bold', kind === s.id ? 'bg-primary text-primary-fg' : 'bg-soft text-primary')}>
              <Icon name={s.icon} size={14} />{s.label}
            </button>
          ))}
        </div>
        {kind === 'link' && (
          <div className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-[1fr_160px]">
              <div>
                <label className="label" htmlFor="nc-url">{t('newCheck.repoUrl')}</label>
                <Input id="nc-url" value={url} autoFocus placeholder="https://github.com/team/service" invalid={!!repoHint}
                  onChange={(e) => setUrl(e.target.value)} />
              </div>
              <div>
                <label className="label" htmlFor="nc-ref">{t('newCheck.branch')}</label>
                <Input id="nc-ref" value={ref} placeholder="main" onChange={(e) => setRef(e.target.value)} />
              </div>
            </div>
            {repoHint && <p className="text-[13px] text-danger" role="alert">{repoHint}</p>}
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              <span>{t('newCheck.confirm')}<span className="block text-[12px] text-muted">{t('newCheck.confirmHint')}</span></span>
            </label>
          </div>
        )}
        {kind === 'archive' && (
          <div>
            <label className="label" htmlFor="nc-upload">{t('wf.archive')}</label>
            <UploadField id="nc-upload" value={uploadId} onChange={setUploadId} />
            <p className="mt-1 text-[12px] text-muted">{t('wf.hintUpload')}</p>
          </div>
        )}
        {kind === 'training' && <p className="rounded-field bg-soft px-3 py-2 text-sm text-primary">{t('wf.hintTraining')}</p>}
      </section>

      {mode === 'create' && (
        <section aria-labelledby="nc-how" className="mt-5">
          <h3 id="nc-how" className="mb-2 text-base font-bold">2. {t('newCheck.how')}</h3>
          <div className="grid gap-2 sm:grid-cols-3">
            {tpl.data && (
              <button type="button" className={card(start.kind === 'template')} onClick={() => setStart({ kind: 'template', id: tpl.data!.id })}>
                <span className="flex items-center gap-1.5 font-bold"><Icon name="template" size={14} />{tpl.data.name}</span>
                <span className="mt-1 line-clamp-2 text-[12px] text-muted">{tpl.data.description}</span>
              </button>
            )}
            {(starters.data ?? []).map((s, i) => (
              <button key={s.id} type="button" className={card(start.kind === 'starter' && start.id === s.id)} onClick={() => setStart({ kind: 'starter', id: s.id })}>
                <span className="font-bold">{s.title}{i === 0 && !tpl.data && <span className="ml-1.5 rounded-chip bg-primary px-1.5 py-0.5 text-[10px] font-bold text-primary-fg">{t('newCheck.recommended')}</span>}</span>
                <span className="mt-1 text-[12px] text-muted">{s.description}</span>
              </button>
            ))}
            <button type="button" className={card(start.kind === 'blank')} onClick={() => setStart({ kind: 'blank' })}>
              <span className="flex items-center gap-1.5 font-bold"><Icon name="workflow" size={14} />{t('newCheck.blank')}</span>
              <span className="mt-1 text-[12px] text-muted">{t('newCheck.blankHint')}</span>
            </button>
            <button type="button" className={card(start.kind === 'prompt')} onClick={() => setStart({ kind: 'prompt' })}>
              <span className="flex items-center gap-1.5 font-bold"><Icon name="sparkles" size={14} />{t('newCheck.prompt')}</span>
              <span className="mt-1 text-[12px] text-muted">{t('newCheck.promptHint')}</span>
            </button>
          </div>
          {start.kind === 'prompt' && (
            <div className="mt-3">
              <label className="label" htmlFor="nc-prompt">{t('newCheck.promptLabel')}</label>
              <Textarea id="nc-prompt" className="font-sans text-sm" value={prompt} placeholder={t('newCheck.promptExample')} onChange={(e) => setPrompt(e.target.value)} />
            </div>
          )}
        </section>
      )}
    </Modal>
  )
}
