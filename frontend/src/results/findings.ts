import type { Finding, Run, Severity } from '../api/types'

export const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
export type DiffFilter = 'new' | 'existing' | 'all'

export function filterFindings(list: Finding[], f: { diff: DiffFilter; severity?: Severity; category?: string }): Finding[] {
  return list.filter((x) => (f.diff === 'all' || x.diff_status === f.diff)
    && (!f.severity || x.severity === f.severity) && (!f.category || x.category === f.category))
}

/** New findings first, then by severity, then by file. */
export function sortFindings(list: Finding[]): Finding[] {
  return [...list].sort((a, b) => (a.diff_status === 'new' ? 0 : 1) - (b.diff_status === 'new' ? 0 : 1)
    || SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
    || a.path.localeCompare(b.path))
}

/** PR verdict of a finished run: diff verdict / CI gate / failed run; null when nothing decides PR blocking. */
export function runVerdict(r: Pick<Run, 'status' | 'gate' | 'verdict'>): 'pass' | 'fail' | null {
  if (r.status === 'failed') return 'fail'
  if (r.status !== 'success') return null
  const v = (r.verdict as { verdict?: string } | null)?.verdict
  if (v) return v === 'FAIL' ? 'fail' : 'pass'
  return r.gate ?? null
}

/** What goes into submission.json, report.md and report.html (confidence ≥ the export threshold) vs. what is only
 *  visible in the interface; both readable reports must show the same findings as the JSON. */
export function splitOfficial(list: Finding[]): { official: Finding[]; below: Finding[] } {
  return { official: list.filter((x) => x.official !== false), below: list.filter((x) => x.official === false) }
}

export function severityCounts(list: Finding[]): Partial<Record<Severity, number>> {
  const out: Partial<Record<Severity, number>> = {}
  for (const x of list) out[x.severity] = (out[x.severity] ?? 0) + 1
  return out
}
