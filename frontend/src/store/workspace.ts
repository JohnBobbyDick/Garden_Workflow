import { create } from 'zustand'

/* Layout state of the workspace screen, remembered between visits. */
interface WorkspaceState {
  railCollapsed: boolean
  inspectorCollapsed: boolean
  lastWorkflowId: string | null
  toggleRail: () => void
  toggleInspector: () => void
  setInspectorCollapsed: (v: boolean) => void
  setLastWorkflow: (id: string | null) => void
}

const read = (k: string) => localStorage.getItem(`aisw.ws.${k}`)
const write = (k: string, v: string | null) => (v === null ? localStorage.removeItem(`aisw.ws.${k}`) : localStorage.setItem(`aisw.ws.${k}`, v))

export const useWorkspaceUi = create<WorkspaceState>((set, get) => ({
  railCollapsed: read('rail') === '1',
  inspectorCollapsed: read('inspector') === '1',
  lastWorkflowId: read('last'),
  toggleRail: () => { const v = !get().railCollapsed; write('rail', v ? '1' : '0'); set({ railCollapsed: v }) },
  toggleInspector: () => { const v = !get().inspectorCollapsed; write('inspector', v ? '1' : '0'); set({ inspectorCollapsed: v }) },
  setInspectorCollapsed: (v) => { write('inspector', v ? '1' : '0'); set({ inspectorCollapsed: v }) },
  setLastWorkflow: (id) => { write('last', id); set({ lastWorkflowId: id }) },
}))
