import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError, withWs } from '../api/client'
import { useWorkflows, useWs } from '../api/hooks'
import { Page } from '../components/layout/AppShell'
import { Badge, Button, Card, CopyButton, Field, Input, PageHeader, Select, Switch, Tabs } from '../components/ui'
import { useLang } from '../i18n'
import { fmtDate } from '../lib/format'
import { toast } from '../store/toast'

interface Delivery { id: string; provider: string; event: string; delivery_id: string; run_ids: string[]; created_at: string }
interface StatusReport { id: string; run_id: string; provider: string; kind: string; state: string; target: string; response_code: number | null; error: string | null; created_at: string }

interface Token { id: string; name: string; prefix: string; workflow_id: string | null; created_at: string; last_used_at: string | null; revoked: boolean }

export default function IntegrationPage() {
  const { t } = useTranslation()
  const lang = useLang()
  const ws = useWs()
  const wfs = useWorkflows()
  const [wf, setWf] = useState('')
  const [provider, setProvider] = useState<'github' | 'gitlab'>('github')
  const [name, setName] = useState('ci')
  const [restrict, setRestrict] = useState(true)
  const [fresh, setFresh] = useState<string | null>(null)
  useEffect(() => { if (!wf && wfs.data?.length) setWf(wfs.data[0].id) }, [wf, wfs.data])
  const yaml = useQuery({ queryKey: ['yaml', provider, wf], enabled: !!wf, queryFn: () => api<string>(`/api/ci/yaml?provider=${provider}&workflow_id=${wf}`) })
  const hooks = useQuery({ queryKey: ['webhook-status', ws], refetchInterval: 15_000,
    queryFn: () => api<{ deliveries: Delivery[]; statuses: StatusReport[] }>(withWs('/api/ci/webhooks/status', ws)) })
  const tokens = useQuery({ queryKey: ['tokens', ws], queryFn: () => api<Token[]>(withWs('/api/api-tokens', ws)) })
  const create = async () => {
    try {
      const r = await api<{ token: string }>('/api/api-tokens', { method: 'POST', json: { workspace_id: ws, name, workflow_id: restrict ? wf || null : null } })
      setFresh(r.token)
      void tokens.refetch()
    } catch (e) { toast.error(e instanceof ApiError ? e.message : String(e)) }
  }
  const revoke = async (id: string) => { await api(`/api/api-tokens/${id}`, { method: 'DELETE' }); void tokens.refetch() }
  const origin = window.location.origin
  return (
    <Page wide>
      <PageHeader title={t('integration.title')} />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title={t('integration.yaml')} className="xl:col-span-2" actions={yaml.data ? <CopyButton text={yaml.data} /> : null}>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1"><Field label={t('integration.workflow')} htmlFor="ci-wf">
              <Select id="ci-wf" value={wf} onChange={(e) => setWf(e.target.value)}>{(wfs.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Field></div>
            <Tabs label="provider" value={provider} onChange={setProvider} tabs={[{ id: 'github', label: 'GitHub Actions' }, { id: 'gitlab', label: 'GitLab CI' }]} />
          </div>
          <pre className="max-h-[480px] overflow-auto rounded-lg border border-border bg-surface-2 p-3 font-mono text-xs">{yaml.data ?? '…'}</pre>
          <p className="mt-2 text-xs text-muted">{provider === 'github' ? '.github/workflows/aisw.yml' : '.gitlab-ci.yml'} · {t('integration.cliHint')}</p>
        </Card>
        <div className="space-y-4">
          <Card title={t('integration.steps')}>
            <ol className="list-decimal space-y-2 pl-5 text-sm">{['step1', 'step2', 'step3'].map((s) => <li key={s}>{t(`integration.${s}`)}</li>)}</ol>
          </Card>
          <Card title={t('integration.webhooks')}>
            <p className="mb-2 text-xs text-muted">{t('integration.webhookHint')}</p>
            {['github', 'gitlab'].map((p) => (
              <div key={p} className="mb-1 flex items-center gap-2"><code className="flex-1 truncate rounded bg-surface-2 px-2 py-1 text-xs">{origin}/api/v1/webhooks/{p}</code>
                <CopyButton text={`${origin}/api/v1/webhooks/${p}`} label="" /></div>
            ))}
            <div className="mt-3 border-t border-border pt-3">
              <div className="mb-2 text-xs font-semibold">{t('integration.deliveries')}</div>
              {!hooks.data?.deliveries.length && !hooks.data?.statuses.length
                ? <p className="text-xs text-muted">{t('integration.noDeliveries')}</p> : (
                  <ul className="max-h-60 space-y-1 overflow-y-auto text-xs">
                    {hooks.data?.deliveries.map((d) => (
                      <li key={d.id} className="flex flex-wrap items-center gap-2">
                        <Badge>{d.provider}</Badge><span className="font-mono">{d.event}</span>
                        <span className="text-muted">{fmtDate(d.created_at, lang)}</span>
                        {d.run_ids.length ? d.run_ids.map((r) => <Link key={r} className="text-primary" to={`/runs/${r}`}>#{r.slice(0, 6)}</Link>)
                          : <span className="text-muted">— {t('integration.runs')}: 0</span>}
                      </li>
                    ))}
                    {hooks.data?.statuses.map((r) => (
                      <li key={r.id} className="flex flex-wrap items-center gap-2" title={r.error ?? r.target}>
                        <Badge tone={r.error ? 'danger' : r.state === 'success' ? 'success' : r.state === 'pending' ? 'info' : 'warning'}>{r.kind}: {r.state}</Badge>
                        <span className="truncate font-mono text-muted">{r.target}</span>
                        <span className={r.error ? 'text-danger' : 'text-muted'}>HTTP {r.response_code ?? '—'}</span>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          </Card>
        </div>
      </div>
      <Card title={t('integration.tokens')} className="mt-4" padded={false}>
        {fresh && (
          <div role="alert" className="m-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
            <p className="mb-1 font-medium">{t('integration.tokenOnce')}</p>
            <div className="flex items-center gap-2"><code className="flex-1 break-all font-mono text-xs">{fresh}</code><CopyButton text={fresh} /></div>
          </div>
        )}
        <table className="table-base"><thead><tr><th>{t('common.name')}</th><th>Prefix</th><th>{t('integration.workflow')}</th><th>{t('common.created')}</th><th /></tr></thead>
          <tbody>{(tokens.data ?? []).map((tk) => (
            <tr key={tk.id}><td>{tk.name}</td><td className="font-mono text-xs">{tk.prefix}…</td>
              <td className="text-xs">{wfs.data?.find((w) => w.id === tk.workflow_id)?.name ?? '—'}</td><td className="text-muted">{fmtDate(tk.created_at, lang)}</td>
              <td>{tk.revoked ? <Badge tone="danger">{t('integration.revoked')}</Badge> : <Button size="sm" variant="ghost" icon="trash" onClick={() => revoke(tk.id)}>{t('integration.revoke')}</Button>}</td></tr>))}</tbody></table>
        <div className="flex flex-wrap items-center gap-3 p-4">
          <Input aria-label={t('common.name')} className="max-w-xs" value={name} onChange={(e) => setName(e.target.value)} />
          <Switch checked={restrict} onChange={setRestrict} label={t('integration.restrict')} />
          <Button icon="plus" variant="primary" onClick={create}>{t('integration.newToken')}</Button>
        </div>
      </Card>
    </Page>
  )
}
