import { createStore } from 'zustand/vanilla'
import type { Edit } from '../types'

export function createHistory(initial: Edit) {
  interface History {
    edit: Edit
    past: Edit[]
    future: Edit[]
    change: (next: Partial<Edit>) => void
    undo: () => void
    redo: () => void
  }
  return createStore<History>((set) => ({
    edit: initial, past: [], future: [],
    change: (next) => set(state => ({
      edit: { ...state.edit, ...next },
      past: [...state.past.slice(-79), state.edit],
      future: [],
    })),
    undo: () => set(state => state.past.length ? {
      past: state.past.slice(0, -1),
      edit: state.past[state.past.length - 1],
      future: [state.edit, ...state.future],
    } : state),
    redo: () => set(state => state.future.length ? {
      past: [...state.past, state.edit], edit: state.future[0], future: state.future.slice(1),
    } : state),
  }))
}

