import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { api, apiFetch, ApiError } from '../api/client'
import { useInvalidate, useProjects, useWs } from '../api/hooks'
import type { Project } from '../api/types'
import { Page } from '../components/layout/AppShell'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton } from '../components/ui'
import { useLang } from '../i18n'
import { fmtDate } from '../lib/format'
import { toast } from '../store/toast'

function ProjectForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const ws = useWs()
  const invalidate = useInvalidate()
  const [form, setForm] = useState({ name: '', description: '', source_mode: 'upload' as Project['source_mode'], git_url: '', ref: '', path: '', subdir: '' })
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      let upload_id: string | undefined
      if (form.source_mode === 'upload') {
        if (!file) throw new Error(t('projects.file'))
        const fd = new FormData()
        fd.append('file', file)
        if (ws) fd.append('workspace_id', ws)
        const r = await apiFetch('/api/uploads', { method: 'POST', body: fd })
        upload_id = (await r.json()).id
        toast.success(t('projects.uploaded'))
      }
      await api('/api/projects', { method: 'POST', json: {
        workspace_id: ws, name: form.name, description: form.description, source_mode: form.source_mode,
        git_url: form.git_url || null, ref: form.ref || null, path: form.path || null, subdir: form.subdir || null, upload_id,
      } })
      await invalidate('projects')
      onDone()
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : t('common.unknownError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Field label={t('common.name')} required htmlFor="p-name"><Input id="p-name" value={form.name} onChange={(e) => set('name', e.target.value)} /></Field>
      <Field label={t('common.description')} htmlFor="p-desc"><Input id="p-desc" value={form.description} onChange={(e) => set('description', e.target.value)} /></Field>
      <Field label={t('projects.source')} htmlFor="p-mode">
        <Select id="p-mode" value={form.source_mode} onChange={(e) => set('source_mode', e.target.value)}>
          <option value="upload">{t('projects.upload')}</option>
          <option value="git_url">{t('projects.gitUrl')}</option>
          <option value="path">{t('projects.path')}</option>
        </Select>
      </Field>
      {form.source_mode === 'upload' && (
        <Field label={t('projects.file')} htmlFor="p-file" required>
          <Input id="p-file" type="file" accept=".zip,.tar,.tgz,.gz" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
      )}
      {form.source_mode === 'git_url' && (
        <>
          <Field label={t('projects.gitUrl')} htmlFor="p-git" required hint={t('projects.allowlistHint')}>
            <Input id="p-git" placeholder="https://github.com/TBagirov/training" value={form.git_url} onChange={(e) => set('git_url', e.target.value)} />
          </Field>
          <Field label={t('projects.ref')} htmlFor="p-ref"><Input id="p-ref" placeholder="main" value={form.ref} onChange={(e) => set('ref', e.target.value)} /></Field>
        </>
      )}
      {form.source_mode === 'path' && (
        <Field label={t('projects.path')} htmlFor="p-path" required><Input id="p-path" value={form.path} onChange={(e) => set('path', e.target.value)} /></Field>
      )}
      <Field label={t('projects.subdir')} htmlFor="p-sub" hint="training-project"><Input id="p-sub" value={form.subdir} onChange={(e) => set('subdir', e.target.value)} /></Field>
      {error && <p role="alert" className="mb-3 rounded-field bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>{t('common.cancel')}</Button>
        <Button variant="primary" loading={busy} disabled={!form.name} onClick={submit}>{t('common.create')}</Button>
      </div>
    </>
  )
}

export default function ProjectsPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const projects = useProjects()
  const invalidate = useInvalidate()
  const [params, setParams] = useSearchParams()
  const open = params.get('new') === '1'
  const close = () => setParams({})

  const remove = async (p: Project) => {
    if (!window.confirm(`${t('common.delete')} «${p.name}»?`)) return
    await api(`/api/projects/${p.id}`, { method: 'DELETE' })
    await invalidate('projects')
  }

  return (
    <Page>
      <PageHeader title={t('projects.title')} actions={<Button icon="plus" variant="primary" onClick={() => setParams({ new: '1' })}>{t('projects.new')}</Button>} />
      {projects.error && <ErrorState error={projects.error} onRetry={() => projects.refetch()} />}
      <Card padded={false}>
        {projects.isLoading ? <div className="space-y-2 p-4">{[1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
          : !projects.data?.length ? (
            <EmptyState icon="folder" title={t('projects.empty')} hint={t('projects.emptyHint')}
              action={<Button icon="plus" variant="primary" onClick={() => setParams({ new: '1' })}>{t('projects.new')}</Button>} />
          ) : (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead><tr><th>{t('common.name')}</th><th>{t('projects.source')}</th><th>{t('common.created')}</th><th className="w-24">{t('common.actions')}</th></tr></thead>
                <tbody>
                  {projects.data.map((p) => (
                    <tr key={p.id}>
                      <td><div className="font-medium">{p.name}</div><div className="text-xs text-muted">{p.description}</div></td>
                      <td>
                        <Badge tone="info">{p.source_mode}</Badge>{' '}
                        <span className="font-mono text-xs text-muted">{p.git_url ?? p.path ?? ''}{p.subdir ? ` / ${p.subdir}` : ''}</span>
                      </td>
                      <td className="text-muted">{fmtDate(p.created_at, lang)}</td>
                      <td><Button size="sm" variant="ghost" icon="trash" aria-label={t('common.delete')} onClick={() => remove(p)} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
      <Modal open={open} onClose={close} title={t('projects.new')}><ProjectForm onDone={close} /></Modal>
    </Page>
  )
}
