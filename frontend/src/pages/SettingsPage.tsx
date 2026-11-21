import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useState } from 'react'
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

const ProjectsPage = lazy(() => import('./ProjectsPage'))

type Tab = 'ai' | 'credentials' | 'allowlist' | 'members' | 'schedules' | 'projects' | 'preferences'
const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : String(e))

type Provider = 'nvidia' | 'ollama'
interface AISettings { enabled: boolean; provider: Provider; base_url: string; model: string; credential_id: string | null;
  headers: Record<string, string>; timeout: number; json_mode: string; allow_local: boolean; ollama_defaults: { base_url: string; model: string }; requires_reconfiguration?: boolean
  credential_ids: string[]; proxy_credential_ids: string[]; fallback_models: string[]; proxy_scheme: string
  proxy_port: string | null; max_retries: number | null; env_default: { enabled: boolean; provider: Provider | ''; model: string } }
interface DiagRow { proxy: string; scheme: string | null; ok: boolean; ms: number; error: string | null }

const NVIDIA = { base_url: 'https://integrate.api.nvidia.com/v1', model: 'nvidia/nemotron-3.5-lightning-30b-a3b' }
const PROVIDERS = { nvidia: 'NVIDIA Nemotron', ollama: 'Ollama' } as const
const PROXY_SCHEMES = ['auto', 'http', 'https', 'socks5', 'socks5h']

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id]
}

function PoolSection({ form, set, admin }: { form: AISettings; set: <K extends keyof AISettings>(k: K, v: AISettings[K]) => void; admin: boolean }) {
  const { t } = useTranslation()
  const ws = useWs()
  const creds = useCredentials()
  const invalidate = useInvalidate()
  const [proxy, setProxy] = useState({ name: '', value: '' })
  const keys = (creds.data ?? []).filter((c) => c.kind === 'llm_api_key' && c.id !== form.credential_id)
  const proxies = (creds.data ?? []).filter((c) => c.kind === 'proxy')
  const addProxy = async () => {
    try {
      const c = await api<{ id: string }>('/api/credentials', { method: 'POST', json: { workspace_id: ws, kind: 'proxy', ...proxy } })
      setProxy({ name: '', value: '' })
      await invalidate('credentials')
      set('proxy_credential_ids', [...form.proxy_credential_ids, c.id])
    } catch (e) { err(e) }
  }
  return (
    <fieldset disabled={!admin} className="min-w-0 space-y-3 pt-3">
      <p className="mb-3 text-xs text-muted">{t('settings.poolHint')}</p>
      <div className="mb-3">
        <div className="label">{t('settings.extraKeys')}</div>
        {keys.length ? keys.map((c) => (
          <label key={c.id} className="flex flex-wrap items-center gap-2 text-sm [overflow-wrap:anywhere]">
            <input type="checkbox" checked={form.credential_ids.includes(c.id)} onChange={() => set('credential_ids', toggle(form.credential_ids, c.id))} />
            {c.name} <span className="font-mono text-muted">{c.display}</span>
          </label>
        )) : <p className="text-xs text-muted">{t('settings.noExtraKeys')}</p>}
      </div>
      <div className="mb-3">
        <div className="label">{t('settings.proxies')}</div>
        {proxies.map((c) => (
          <label key={c.id} className="flex flex-wrap items-center gap-2 text-sm [overflow-wrap:anywhere]">
            <input type="checkbox" checked={form.proxy_credential_ids.includes(c.id)} onChange={() => set('proxy_credential_ids', toggle(form.proxy_credential_ids, c.id))} />
            {c.name} <span className="font-mono text-muted">{c.display}</span>
          </label>
        ))}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input className="min-w-0 flex-[1_1_9rem]" aria-label={t('settings.proxyName')} placeholder={t('settings.proxyName')} value={proxy.name} onChange={(e) => setProxy({ ...proxy, name: e.target.value })} />
          <Input className="min-w-0 flex-[2_1_12rem]" aria-label={t('settings.proxyValue')} type="password" autoComplete="off" placeholder="host:port:login:password" value={proxy.value} onChange={(e) => setProxy({ ...proxy, value: e.target.value })} />
          <Button icon="plus" disabled={!proxy.name || !proxy.value} onClick={addProxy}>{t('settings.addProxy')}</Button>
        </div>
        <p className="mt-1 text-xs text-muted">{t('settings.proxyFormats')}</p>
      </div>
      <div className="grid gap-x-3 [grid-template-columns:repeat(auto-fit,minmax(min(9rem,100%),1fr))]">
        <Field label={t('settings.proxyScheme')} htmlFor="ai-ps">
          <Select id="ai-ps" value={form.proxy_scheme} onChange={(e) => set('proxy_scheme', e.target.value)}>{PROXY_SCHEMES.map((x) => <option key={x}>{x}</option>)}</Select>
        </Field>
        <Field label={t('settings.proxyPort')} htmlFor="ai-pp"><Input id="ai-pp" inputMode="numeric" value={form.proxy_port ?? ''} onChange={(e) => set('proxy_port', e.target.value.replace(/\D/g, '') || null)} /></Field>
        <Field label={t('settings.retries')} htmlFor="ai-r" hint={t('settings.retriesHint')}>
          <Input id="ai-r" inputMode="numeric" value={form.max_retries ?? ''} placeholder="auto"
            onChange={(e) => { const n = parseInt(e.target.value, 10); set('max_retries', Number.isFinite(n) ? Math.min(6, Math.max(1, n)) : null) }} />
        </Field>
      </div>
    </fieldset>
  )
}

function DiagnoseTable({ rows }: { rows: DiagRow[] }) {
  const { t } = useTranslation()
  return (
    <div className="mb-3 overflow-x-auto"><table className="table-base" aria-label={t('settings.diagnose')}>
      <thead><tr><th>{t('settings.diagProxy')}</th><th>{t('settings.proxyScheme')}</th><th>{t('settings.diagResult')}</th><th>{t('settings.diagTime')}</th><th>{t('settings.diagReason')}</th></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}><td className="font-mono">{r.proxy === 'direct' ? t('settings.direct') : r.proxy}</td><td>{r.scheme ?? '—'}</td>
          <td><Badge tone={r.ok ? 'success' : 'danger'}>{r.ok ? 'OK' : 'FAIL'}</Badge></td><td className="tabular-nums">{r.ms} {t('settings.ms')}</td>
          <td className="text-xs text-muted">{r.error ?? ''}</td></tr>))}</tbody>
    </table></div>
  )
}

function AiTab({ admin, canTest }: { admin: boolean; canTest: boolean }) {
  const { t } = useTranslation()
  const ws = useWs()
  const creds = useCredentials()
  const client = useQueryClient()
  const q = useQuery({ queryKey: ['ai-settings', ws], refetchOnWindowFocus: false, queryFn: () => api<AISettings>(withWs('/api/settings/ai', ws)) })
  const [form, setForm] = useState<AISettings | null>(null)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<'save' | 'test' | 'diag' | null>(null)
  const [diag, setDiag] = useState<{ rows: DiagRow[]; error: string | null } | null>(null)
  useEffect(() => { if (q.data) setForm(q.data) }, [q.data])
  if (q.error) return <ErrorState error={q.error} />
  if (!form) return <Skeleton className="h-64" />
  const clearChecks = () => { setResult(null); setDiag(null) }
  const set = <K extends keyof AISettings>(k: K, v: AISettings[K]) => {
    clearChecks()
    setForm((f) => (f ? { ...f, [k]: v } : f))
  }
  const { env_default: platform } = form
  const selected = !form.enabled && platform.enabled && platform.provider ? platform.provider : form.provider
  const choose = (provider: Provider) => {
    if (provider === form.provider) {
      set('enabled', true)
      return
    }
    clearChecks()
    const defaults = provider === 'nvidia' ? NVIDIA : form.ollama_defaults
    setForm({ ...form, ...defaults, provider, enabled: true, allow_local: provider === 'ollama',
      credential_id: null, credential_ids: [], proxy_credential_ids: [], fallback_models: [], headers: {},
      proxy_scheme: 'auto', proxy_port: null, max_retries: null })
  }
  const persist = async () => {
    const { enabled, provider, base_url, model, allow_local, credential_id, credential_ids,
      proxy_credential_ids, proxy_scheme, proxy_port, max_retries, timeout, json_mode } = form
    const sameEndpoint = provider === q.data?.provider && base_url.trim() === q.data.base_url
    const workspaceAuth = provider === 'ollama' || !!credential_id || credential_ids.length > 0
    const saved = await api<AISettings>('/api/settings/ai', { method: 'PUT', json: {
      workspace_id: ws, enabled, provider, timeout, json_mode,
      ...(provider === 'nvidia' ? { ...NVIDIA, allow_local: false, credential_id, credential_ids, proxy_credential_ids,
        proxy_scheme, proxy_port, max_retries } : { base_url: base_url.trim(), model: model.trim(), allow_local,
        credential_id: sameEndpoint ? credential_id : null, credential_ids: [], proxy_credential_ids: [], proxy_scheme: 'auto', proxy_port: null, max_retries: null }),
      headers: sameEndpoint && workspaceAuth ? form.headers : {}, fallback_models: [],
    } })
    client.setQueryData(['ai-settings', ws], saved)
    setForm(saved)
  }
  const save = async () => {
    setBusy('save')
    try { await persist(); toast.success(t('settings.saved')) } catch (e) { err(e) } finally { setBusy(null) }
  }
  const test = async () => {
    setBusy('test')
    try {
      if (admin) await persist()
      const r = await api<{ ok: boolean; model?: string; latency_ms?: number; error?: string }>('/api/settings/ai/test', { method: 'POST', json: { workspace_id: ws } })
      setResult({ ok: r.ok, text: r.ok ? t('settings.testOk', { model: r.model, ms: r.latency_ms }) : t('settings.testFail', { error: r.error }) })
    } catch (e) { err(e) } finally { setBusy(null) }
  }
  const runDiag = async () => {
    setBusy('diag')
    try {
      if (admin) await persist()
      const r = await api<{ results: DiagRow[]; error: string | null }>('/api/settings/ai/diagnose', { method: 'POST', json: { workspace_id: ws } })
      setDiag({ rows: r.results, error: r.error })
    } catch (e) { err(e) } finally { setBusy(null) }
  }
  return (
    <Card title={t('settings.ai')} className="min-w-0">
      {form.requires_reconfiguration && <p className="mb-3 text-sm text-warning">{t('settings.reconfigure')}</p>}
      <fieldset disabled={!admin || !!busy} className="min-w-0 space-y-4">
        <fieldset className="min-w-0">
          <legend className="label">{t('settings.provider')}</legend>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(PROVIDERS) as Provider[]).map((p) => (
              <label key={p} className={`flex cursor-pointer items-center gap-2 rounded-field border px-3 py-2 text-sm ${selected === p ? 'border-primary bg-soft text-primary' : 'border-border'}`}>
                <input type="radio" name="ai-provider" value={p} checked={selected === p} readOnly onClick={() => choose(p)} />
                {PROVIDERS[p]}
              </label>
            ))}
          </div>
        </fieldset>
        <Switch checked={form.enabled} onChange={(v) => v ? choose(selected) : set('enabled', false)} label={t('settings.workspaceProvider')} />
        {!form.enabled && <p role="status" className="rounded-field bg-soft px-3 py-2 text-sm [overflow-wrap:anywhere]">
          {platform.enabled ? t('settings.envDefault', { provider: PROVIDERS[selected], model: platform.model }) : t('settings.aiOff')}
        </p>}
        {form.enabled && (form.provider === 'ollama' ? <>
          <Field label={t('settings.baseUrl')} htmlFor="ai-u"><Input id="ai-u" value={form.base_url} onChange={(e) => set('base_url', e.target.value)} /></Field>
          <Field label={t('settings.model')} htmlFor="ai-m"><Input id="ai-m" value={form.model} onChange={(e) => set('model', e.target.value)} /></Field>
          <Switch checked={form.allow_local} onChange={(v) => set('allow_local', v)} label={t('settings.allowLocal')} />
        </> : <>
          <p className="text-sm text-muted [overflow-wrap:anywhere]">{t('settings.model')} · <code>{NVIDIA.model}</code></p>
          <Field label={t('settings.apiKey')} htmlFor="ai-k">
            <Select id="ai-k" value={form.credential_id ?? ''} onChange={(e) => set('credential_id', e.target.value || null)}>
              <option value="">{t('settings.platformKey')}</option>
              {(creds.data ?? []).filter((c) => c.kind === 'llm_api_key').map((c) => <option key={c.id} value={c.id}>{c.name} · {c.display}</option>)}
            </Select>
          </Field>
          <details className="min-w-0 border-t border-border pt-3">
            <summary className="cursor-pointer text-sm font-bold">{t('settings.pool')}</summary>
            <PoolSection form={form} set={set} admin={admin} />
          </details>
        </>)}
      </fieldset>
      {result && <p role="status" className={`mt-3 text-sm [overflow-wrap:anywhere] ${result.ok ? 'text-success' : 'text-danger'}`}>{result.text}</p>}
      {diag && (diag.error ? <p role="status" className="mt-3 text-sm text-danger [overflow-wrap:anywhere]">{diag.error}</p> : <DiagnoseTable rows={diag.rows} />)}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="primary" icon="save" disabled={!admin || !!busy} loading={busy === 'save'} onClick={save}>{t('common.save')}</Button>
        <Button icon="sparkles" disabled={!canTest || !!busy} loading={busy === 'test'} onClick={test}>{t('settings.test')}</Button>
        <Button icon="shield-check" disabled={!canTest || !!busy} loading={busy === 'diag'} onClick={runDiag}>{t('settings.diagnose')}</Button>
        {!admin && <span className="text-xs text-muted">{t('settings.adminOnly')}</span>}
      </div>
    </Card>
  )
}

const KINDS = ['telegram', 'smtp', 'webhook_secret', 'repo_token', 'repo_write_token', 'llm_api_key', 'proxy', 'generic']

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
    <div className="grid gap-4">
      <Card title={t('settings.credentials')} className="min-w-0 overflow-x-auto" padded={false}>
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
    <Card title={t('settings.allowlist')} className="min-w-0 overflow-x-auto" padded={false}>
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
        <div className="flex flex-wrap gap-2 p-4">
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
    <Card title={t('settings.members')} className="min-w-0 overflow-x-auto" padded={false}>
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
    <Card title={t('settings.schedules')} className="min-w-0 overflow-x-auto" padded={false}>
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
  const role = me.data?.workspaces.find((w) => w.id === ws)?.role
  const admin = role === 'admin'
  return (
    <Page wide>
      <PageHeader title={t('settings.title')} />
      <Tabs compact label={t('settings.title')} value={tab} onChange={(v) => setParams((p) => { const n = new URLSearchParams(p); n.set('tab', v); return n })}
        tabs={(['ai', 'credentials', 'allowlist', 'members', 'schedules', 'projects', 'preferences'] as Tab[])
        .map((id) => ({ id, label: t(`settings.${id}`) }))} />
      <div className="mt-4">
        {tab === 'ai' && <AiTab key={ws} admin={admin} canTest={admin || role === 'developer'} />}
        {tab === 'credentials' && <CredentialsTab admin={admin} />}
        {tab === 'allowlist' && <AllowlistTab admin={admin} />}
        {tab === 'members' && <MembersTab admin={admin} />}
        {tab === 'schedules' && <SchedulesTab />}
        {tab === 'projects' && <Suspense fallback={<Skeleton className="h-40" />}><ProjectsPage /></Suspense>}
        {tab === 'preferences' && <PreferencesTab />}
      </div>
    </Page>
  )
}
