import type { NodeSpec } from '../api/types'

const port = (name: string, type: string, extra: Partial<{ required: boolean; multiple: boolean }> = {}) => ({
  name,
  type,
  required: extra.required ?? true,
  multiple: extra.multiple ?? false,
  title: { ru: name, en: name },
})

export const catalog: NodeSpec[] = [
  { type: 'trigger.manual', category: 'trigger', title: { ru: 'Ручной запуск', en: 'Manual' }, description: { ru: '', en: '' },
    icon: 'play', inputs: [], outputs: [port('out', 'trigger')], branch_outputs: [], config_schema: { type: 'object', properties: {} } },
  { type: 'source.repo', category: 'source', title: { ru: 'Код', en: 'Code' }, description: { ru: '', en: '' }, icon: '',
    inputs: [port('in', 'trigger')], outputs: [port('out', 'repo')], branch_outputs: [], config_schema: { type: 'object', properties: {} } },
  { type: 'scanner.sast', category: 'scanner', title: { ru: 'SAST', en: 'SAST' }, description: { ru: '', en: '' }, icon: '',
    inputs: [port('in', 'repo')], outputs: [port('out', 'findings')], branch_outputs: [], config_schema: { type: 'object', properties: {} } },
  { type: 'logic.merge', category: 'logic', title: { ru: 'Слияние', en: 'Merge' }, description: { ru: '', en: '' }, icon: '',
    inputs: [port('in', 'findings', { multiple: true })], outputs: [port('out', 'findings')], branch_outputs: [],
    config_schema: { type: 'object', properties: {} } },
  { type: 'logic.if_else', category: 'logic', title: { ru: 'Условие', en: 'IF' }, description: { ru: '', en: '' }, icon: '',
    inputs: [port('in', 'any')], outputs: [port('true', 'any'), port('false', 'any')], branch_outputs: ['true', 'false'],
    config_schema: { type: 'object', properties: { expression: { type: 'string', title: 'Условие', 'x-title-en': 'Condition', 'x-widget': 'expression' } }, required: ['expression'] } },
  { type: 'notify.telegram', category: 'notify', title: { ru: 'Telegram', en: 'Telegram' }, description: { ru: '', en: '' }, icon: '',
    inputs: [port('in', 'any', { multiple: true })], outputs: [port('out', 'json')], branch_outputs: [],
    config_schema: { type: 'object', properties: {} } },
]
