import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError, withWs } from '../api/client'
import { useCredentials, useInvalidate, useMe, useWorkflows, useWs } from '../api/hooks'
import { Page } from '../components/layout/AppShell'
import { Badge, Button, Card, ErrorState, Field, Input, PageHeader, Select, Skeleton, Switch, Tabs } from '../components/ui'
import { useLang } from '../i18n'
import { describeCron } from '../lib/cron'
import { fmtDate } from '../lib/format'
import { toast } from '../store/toast'
import { useUi } from '../store/ui'

type Tab = 'ai' | 'credentials' | 'allowlist' | 'members' | 'schedules' | 'preferences'
const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : String(e))

interface AISettings { enabled: boolean; provider: string; base_url: string; model: string; credential_id: string | null;
  headers: Record<string, string>; timeout: number; json_mode: string; allow_local: boolean; providers: string[]; hints: string[] }

function AiTab({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const ws = useWs()
  const creds = useCredentials()
  const q = useQuery({ queryKey: ['ai-settings', ws], queryFn: () => api<AISettings>(withWs('/api/settings/ai', ws)) })
  const [form, setForm] = useState<AISettings | null>(null)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<'save' | 'test' | null>(null)
  useEffect(() => { if (q.data) setForm(q.data) }, [q.data])
  if (q.error) return <ErrorState error={q.error} />
  if (!form) return <Skeleton className="h-64" />
  const set = <K extends keyof AISettings>(k: K, v: AISettings[K]) => setForm({ ...form, [k]: v })
  const save = async () => {
    setBusy('save')
    try { await api('/api/settings/ai', { method: 'PUT', json: { ...form, workspace_id: ws } }); toast.success(t('settings.saved')) } catch (e) { err(e) } finally { setBusy(null) }
  }
  const test = async () => {
    setBusy('test')
    try {
      await api('/api/settings/ai', { method: 'PUT', json: { ...form, workspace_id: ws } })
      const r = await api<{ ok: boolean; model?: string; latency_ms?: number; error?: string }>('/api/settings/ai/test', { method: 'POST', json: { workspace_id: ws } })
      setResult({ ok: r.ok, text: r.ok ? t('settings.testOk', { model: r.model, ms: r.latency_ms }) : t('settings.testFail', { error: r.error }) })
    } catch (e) { err(e) } finally { setBusy(null) }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title={t('settings.ai')} className="lg:col-span-2">
        <fieldset disabled={!admin} className="space-y-1">
          <div className="mb-3"><Switch checked={form.enabled} onChange={(v) => set('enabled', v)} label={t('settings.enabled')} /></div>
          <Field label={t('settings.provider')} htmlFor="ai-p">
            <Select id="ai-p" value={form.provider} onChange={(e) => set('provider', e.target.value)}>{form.providers.map((p) => <option key={p}>{p}</option>)}</Select>
          </Field>
          <Field label={t('settings.baseUrl')} htmlFor="ai-u"><Input id="ai-u" value={form.base_url} placeholder="http://localhost:11434" onChange={(e) => set('base_url', e.target.value)} /></Field>
          <Field label={t('settings.model')} htmlFor="ai-m"><Input id="ai-m" value={form.model} placeholder="qwen2.5:7b" onChange={(e) => set('model', e.target.value)} /></Field>
          <Field label={t('settings.apiKey')} htmlFor="ai-k">
            <Select id="ai-k" value={form.credential_id ?? ''} onChange={(e) => set('credential_id', e.target.value || null)}>
              <option value="">—</option>
              {(creds.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} · {c.display}</option>)}
            </Select>
          </Field>
          <div className="mb-3"><Switch checked={form.allow_local} onChange={(v) => set('allow_local', v)} label={t('settings.allowLocal')} /></div>
        </fieldset>
        {result && <p role="status" className={result.ok ? 'mb-3 text-sm text-success' : 'mb-3 text-sm text-danger'}>{result.text}</p>}
        <div className="flex gap-2">
          <Button variant="primary" icon="save" disabled={!admin} loading={busy === 'save'} onClick={save}>{t('common.save')}</Button>
          <Button icon="sparkles" disabled={!admin} loading={busy === 'test'} onClick={test}>{t('settings.test')}</Button>
          {!admin && <span className="self-center text-xs text-muted">{t('settings.adminOnly')}</span>}
        </div>
      </Card>
      <Card title={t('settings.freeHints')}><ul className="space-y-2 text-sm text-muted">{form.hints.map((h) => <li key={h}>• {h}</li>)}</ul></Card>
    </div>
  )
}

const KINDS = ['telegram', 'smtp', 'webhook_secret', 'repo_token', 'repo_write_token', 'llm_api_key', 'generic']

function CredentialsTab({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const creds = useCredentials()
  const invalidate = useInvalidate()
  const [f, setF] = useState({ name: '', kind: 'telegram', value: '' })
  const create = async () => {
    try {
      await api('/api/credentials', { method: 'POST', json: { ...f, workspace_id: ws } })
      setF({ name: '', kind: f.kind, value: '' })
      toast.success(t('settings.credentialSaved'))
      await invalidate('credentials')
    } catch (e) { err(e) }
  }
  const remove = async (id: string) => {
    if (!window.confirm(t('common.confirm'))) return
    try { await api(`/api/credentials/${id}`, { method: 'DELETE' }); await invalidate('credentials') } catch (e) { err(e) }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title={t('settings.credentials')} className="lg:col-span-2" padded={false}>
        <p className="px-4 pt-3 text-xs text-muted">{t('settings.writeOnly')}</p>
        <table className="table-base"><thead><tr><th>{t('common.name')}</th><th>{t('settings.credentialKind')}</th><th>{t('settings.credentialValue')}</th><th>{t('common.created')}</th><th /></tr></thead>
          <tbody>{(creds.data ?? []).map((c) => (
            <tr key={c.id}><td className="font-medium">{c.name}</td><td><Badge>{c.kind}</Badge></td><td className="font-mono">{c.display}</td>
              <td className="text-muted">{fmtDate(c.created_at, lang)}</td>
              <td>{admin && <Button size="sm" variant="ghost" icon="trash" aria-label={t('common.delete')} onClick={() => remove(c.id)} />}</td></tr>))}</tbody></table>
      </Card>
      <Card title={t('settings.newCredential')}>
        <fieldset disabled={!admin}>
          <Field label={t('common.name')} htmlFor="c-n" required><Input id="c-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label={t('settings.credentialKind')} htmlFor="c-k"><Select id="c-k" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label={t('settings.credentialValue')} htmlFor="c-v" required><Input id="c-v" type="password" autoComplete="off" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></Field>
          <Button variant="primary" icon="plus" disabled={!f.name || !f.value} onClick={create}>{t('common.create')}</Button>
        </fieldset>
        {!admin && <p className="mt-2 text-xs text-muted">{t('settings.adminOnly')}</p>}
      </Card>
    </div>
  )
}

interface AllowEntry { url: string; allow_write: boolean; provider: string; api_base: string | null; readonly?: boolean }

function AllowlistTab({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const ws = useWs()
  const q = useQuery({ queryKey: ['allowlist', ws], queryFn: () => api<{ platform: AllowEntry[]; entries: AllowEntry[] }>(withWs('/api/settings/allowlist', ws)) })
  const [entries, setEntries] = useState<AllowEntry[]>([])
  const [url, setUrl] = useState('')
  useEffect(() => { if (q.data) setEntries(q.data.entries) }, [q.data])
  const save = async (next: AllowEntry[]) => {
    try {
      const r = await api<{ entries: AllowEntry[] }>('/api/settings/allowlist', { method: 'PUT', json: { workspace_id: ws, entries: next.map(({ readonly: _r, ...e }) => e) } })
      setEntries(r.entries)
      toast.success(t('settings.saved'))
    } catch (e) { err(e); void q.refetch() }
  }
  if (!q.data) return <Skeleton className="h-40" />
  return (
    <Card title={t('settings.allowlist')} padded={false}>
      <table className="table-base"><thead><tr><th>URL</th><th>{t('settings.allowWrite')}</th><th /></tr></thead>
        <tbody>
          {q.data.platform.map((e) => <tr key={e.url}><td className="font-mono text-xs">{e.url}</td><td><Badge>{t('settings.platformRepo')}</Badge></td><td /></tr>)}
          {entries.map((e, i) => (
            <tr key={e.url}><td className="font-mono text-xs">{e.url}</td>
              <td>{e.readonly ? <Badge tone="warning">{t('settings.readonlyRepo')}</Badge>
                : <Switch checked={e.allow_write} onChange={(v) => admin && save(entries.map((x, j) => (j === i ? { ...x, allow_write: v } : x)))} label="" />}</td>
              <td>{admin && <Button size="sm" variant="ghost" icon="trash" aria-label={t('common.delete')} onClick={() => save(entries.filter((_, j) => j !== i))} />}</td></tr>
          ))}
        </tbody></table>
      {admin && (
        <div className="flex gap-2 p-4">
          <Input aria-label="URL" placeholder="https://github.com/org/training-copy" value={url} onChange={(e) => setUrl(e.target.value)} />
          <Button icon="plus" disabled={!url} onClick={() => { void save([...entries, { url, allow_write: false, provider: url.includes('gitlab') ? 'gitlab' : 'github', api_base: null }]); setUrl('') }}>{t('settings.addRepo')}</Button>
        </div>
      )}
    </Card>
  )
}

function MembersTab({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const ws = useWs()
  const q = useQuery({ queryKey: ['members', ws], queryFn: () => api<{ members: { user_id: string; email: string; role: string }[]; invitations: { email: string; role: string }[] }>(`/api/workspaces/${ws}/members`) })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('developer')
  const invite = async () => {
    try {
      const r = await api<{ status: string; invite_token?: string }>(`/api/workspaces/${ws}/members`, { method: 'POST', json: { email, role } })
      if (r.invite_token) toast.info(t('settings.inviteToken', { token: r.invite_token }))
      setEmail('')
      void q.refetch()
    } catch (e) { err(e) }
  }
  const change = async (uid: string, r: string) => { try { await api(`/api/workspaces/${ws}/members/${uid}`, { method: 'PATCH', json: { role: r } }); void q.refetch() } catch (e) { err(e) } }
  const remove = async (uid: string) => { try { await api(`/api/workspaces/${ws}/members/${uid}`, { method: 'DELETE' }); void q.refetch() } catch (e) { err(e) } }
  return (
    <Card title={t('settings.members')} padded={false}>
      <table className="table-base"><thead><tr><th>E-mail</th><th>{t('settings.role')}</th><th /></tr></thead>
        <tbody>
          {(q.data?.members ?? []).map((m) => (
            <tr key={m.user_id}><td>{m.email}</td>
              <td><Select aria-label={t('settings.role')} disabled={!admin} value={m.role} onChange={(e) => change(m.user_id, e.target.value)} className="w-44">
                {['admin', 'developer', 'viewer'].map((r) => <option key={r} value={r}>{t(`settings.roles.${r}`)}</option>)}</Select></td>
              <td>{admin && <Button size="sm" variant="ghost" icon="trash" aria-label={t('common.delete')} onClick={() => remove(m.user_id)} />}</td></tr>))}
          {(q.data?.invitations ?? []).map((i) => <tr key={i.email}><td className="text-muted">{i.email}</td><td><Badge tone="info">{t(`settings.roles.${i.role}`)}</Badge></td><td /></tr>)}
        </tbody></table>
      {admin && (
        <div className="flex flex-wrap gap-2 p-4">
          <Input aria-label="E-mail" type="email" className="max-w-xs" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="dev@example.org" />
          <Select aria-label={t('settings.role')} className="w-44" value={role} onChange={(e) => setRole(e.target.value)}>
            {['developer', 'viewer', 'admin'].map((r) => <option key={r} value={r}>{t(`settings.roles.${r}`)}</option>)}</Select>
          <Button icon="plus" disabled={!email} onClick={invite}>{t('settings.invite')}</Button>
        </div>
      )}
    </Card>
  )
}

function SchedulesTab() {
  const { t } = useTranslation()
  const lang = useLang()
  const wfs = useWorkflows()
  const q = useQuery({
    queryKey: ['schedules', wfs.data?.map((w) => w.id).join()], enabled: !!wfs.data,
    queryFn: async () => (await Promise.all((wfs.data ?? []).map(async (w) => ({ w, s: await api<{ schedules: { id: string; cron: string; timezone: string; enabled: boolean; next_run_at: string | null }[] }>(`/api/workflows/${w.id}/schedule`) }))))
      .flatMap(({ w, s }) => s.schedules.map((x) => ({ ...x, wf: w }))),
  })
  const toggle = async (wfId: string, enabled: boolean) => { await api(`/api/workflows/${wfId}/schedule`, { method: 'PUT', json: { enabled } }); void q.refetch() }
  return (
    <Card title={t('settings.schedules')} padded={false}>
      {!q.data ? <Skeleton className="m-4 h-20" /> : !q.data.length ? <p className="p-4 text-sm text-muted">{t('common.empty')}</p> : (
        <table className="table-base"><thead><tr><th>{t('runs.workflow')}</th><th>Cron</th><th>{t('settings.timezone')}</th><th>{t('settings.nextRun')}</th><th>{t('settings.enabledShort')}</th></tr></thead>
          <tbody>{q.data.map((s) => (
            <tr key={s.id}><td>{s.wf.name}</td><td><code>{s.cron}</code><div className="text-xs text-muted">{describeCron(s.cron, lang)}</div></td><td>{s.timezone}</td>
              <td className="text-muted">{fmtDate(s.next_run_at, lang)}</td><td><Switch checked={s.enabled} onChange={(v) => toggle(s.wf.id, v)} label="" /></td></tr>))}</tbody></table>
      )}
    </Card>
  )
}

function PreferencesTab() {
  const { t } = useTranslation()
  const { theme, setTheme, lang, setLang } = useUi()
  return (
    <Card title={t('settings.preferences')} className="max-w-md">
      <Field label={t('common.theme')} htmlFor="pref-theme">
        <Select id="pref-theme" value={theme} onChange={(e) => setTheme(e.target.value as 'dark' | 'light')}>
          <option value="dark">{t('common.dark')}</option><option value="light">{t('common.light')}</option></Select>
      </Field>
      <Field label={t('common.language')} htmlFor="pref-lang">
        <Select id="pref-lang" value={lang} onChange={(e) => setLang(e.target.value as 'ru' | 'en')}><option value="ru">Русский</option><option value="en">English</option></Select>
      </Field>
    </Card>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const ws = useWs()
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) ?? 'ai'
  const admin = me.data?.workspaces.find((w) => w.id === ws)?.role === 'admin'
  return (
    <Page wide>
      <PageHeader title={t('settings.title')} />
      <Tabs label={t('settings.title')} value={tab} onChange={(v) => setParams({ tab: v })} tabs={(['ai', 'credentials', 'allowlist', 'members', 'schedules', 'preferences'] as Tab[])
        .map((id) => ({ id, label: t(`settings.${id}`) }))} />
      <div className="mt-4">
        {tab === 'ai' && <AiTab admin={admin} />}
        {tab === 'credentials' && <CredentialsTab admin={admin} />}
        {tab === 'allowlist' && <AllowlistTab admin={admin} />}
        {tab === 'members' && <MembersTab admin={admin} />}
        {tab === 'schedules' && <SchedulesTab />}
        {tab === 'preferences' && <PreferencesTab />}
      </div>
    </Page>
  )
}
