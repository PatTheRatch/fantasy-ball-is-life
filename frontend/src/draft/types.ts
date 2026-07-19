import type { DraftPickEntry, DraftPoolParams, DraftPortfolioResponse } from '../api'

export interface StoredState {
  schemaVersion: number
  picks: DraftPickEntry[]
  portfolio: DraftPortfolioResponse | null
  activePlanId: string | null
  params: DraftPoolParams
}
