import type { CustomPlanSpec } from '../api'
import {
  DEFAULT_PARAMS,
  PRESETS_STORAGE_KEY,
  SCHEMA_VERSION,
  STORAGE_KEY,
} from './constants'
import type { StoredState } from './types'

export function loadPresets(): CustomPlanSpec[] {
  try {
    const raw = localStorage.getItem(PRESETS_STORAGE_KEY)
    if (raw) return JSON.parse(raw) as CustomPlanSpec[]
  } catch {
    // corrupt/old localStorage payload — fall through to an empty library
  }
  return []
}

export function loadStored(): StoredState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as StoredState
      if (parsed.schemaVersion === SCHEMA_VERSION) return parsed
    }
  } catch {
    // corrupt/old localStorage payload — fall through to a clean slate
  }
  return { schemaVersion: SCHEMA_VERSION, picks: [], portfolio: null, activePlanId: null, params: DEFAULT_PARAMS }
}
