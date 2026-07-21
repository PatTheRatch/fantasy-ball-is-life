import { describe, expect, it } from 'vitest'
import { inSeasonQueryKeys } from './inSeasonFetch'

describe('inSeasonQueryKeys (N-3 cache isolation)', () => {
  it('includes the slug so two leagues never share a cache entry', () => {
    const a = inSeasonQueryKeys.projected('league-a', 3, '15', '')
    const b = inSeasonQueryKeys.projected('league-b', 3, '15', '')
    expect(a).not.toEqual(b)
    expect(a).toContain('league-a')
    expect(b).toContain('league-b')

    expect(inSeasonQueryKeys.current('league-a', 3)).not.toEqual(
      inSeasonQueryKeys.current('league-b', 3),
    )
    expect(inSeasonQueryKeys.power('league-a', 3)).not.toEqual(
      inSeasonQueryKeys.power('league-b', 3),
    )
  })

  it('slug-scoped invalidation prefix matches only that league', () => {
    const key = inSeasonQueryKeys.projected('league-a', 3, '15', '')
    const prefix = ['in-season', 'projected', 'league-a']
    // React Query prefix-matching semantics: every prefix element equals
    // the key element at the same index.
    expect(prefix.every((part, i) => key[i] === part)).toBe(true)
    const other = inSeasonQueryKeys.projected('league-b', 3, '15', '')
    expect(prefix.every((part, i) => other[i] === part)).toBe(false)
  })
})
