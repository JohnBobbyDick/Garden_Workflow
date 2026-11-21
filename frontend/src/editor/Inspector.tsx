import { useTranslation } from 'react-i18next'
import type { NodeSpec, Run, ValidationIssue } from '../api/types'
import { Button } from '../components/ui'
import { Icon } from '../components/ui/Icon'
import { RunResults } from '../results/RunResults'
import type { FlowNode } from './graphModel'
import { ConfigPanel, RunNodePanel } from './SidePanel'
import type { NodeLive } from './useRunEvents'

/* Right column of the canvas: node settings, node data/logs during a run, or the run results. */
export function Inspector({ node, spec, issues, live, run, onChange, onDelete, onToggle, onCloseRun }: {
  node: FlowNode | null; spec: NodeSpec | undefined; issues: ValidationIssue[]
  live: NodeLive | undefined; run: Run | undefined
  onChange: (patch: Partial<FlowNode['data']>) => void; onDelete: () => void; onToggle: () => void; onCloseRun: () => void
}) {
  const { t } = useTranslation()
  if (node) {
    return (
      <RunNodePanel key={node.id} node={node} live={live}>
        <ConfigPanel node={node} spec={spec} issues={issues} onChange={onChange} />
        <div className="flex gap-2 border-t border-border px-4 py-3">
          <Button size="sm" variant="ghost" icon="power" onClick={onToggle}>{node.data.disabled ? t('editor.enable') : t('editor.disable')}</Button>
          <Button size="sm" variant="ghost" icon="trash" className="text-danger" onClick={onDelete}>{t('editor.deleteNode')}</Button>
        </div>
      </RunNodePanel>
    )
  }
  if (run) return <RunResults run={run} onClose={onCloseRun} />
  return (
    <div className="flex h-full flex-col items-center justify-center p-8 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-card bg-soft text-primary"><Icon name="sparkles" size={22} /></div>
      <p className="font-bold">{t('canvas.inspectorEmptyTitle')}</p>
      <p className="mt-1 text-sm text-muted">{t('canvas.inspectorEmptyHint')}</p>
    </div>
  )
}
