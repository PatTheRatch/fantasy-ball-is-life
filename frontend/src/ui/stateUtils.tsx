import { Loader2 } from 'lucide-react'
import type { StateBlockProps } from './StateBlock'

/* -------------------------------------------------------------------------- */
/* inferStateBlock — derive StateBlock props from React Query result           */
/* -------------------------------------------------------------------------- */

interface InferStateInput {
  isLoading: boolean
  isError: boolean
  error: unknown
  data: unknown
  isEmpty: (data: unknown) => boolean
  fetchedAt?: string | null
  isStale?: boolean
}

export function inferStateBlock(input: InferStateInput): StateBlockProps & { show: boolean } {
  if (input.isLoading) {
    return { state: 'loading', show: true }
  }
  if (input.isError) {
    return { state: 'error', error: input.error, show: true }
  }
  if (input.isStale) {
    return { state: 'stale', fetchedAt: input.fetchedAt, show: true }
  }
  if (input.isEmpty(input.data)) {
    return { state: 'empty', show: true }
  }
  return { state: 'empty', show: false }
}

/* -------------------------------------------------------------------------- */
/* Loading spinner (compact, for inline use like buttons)                      */
/* -------------------------------------------------------------------------- */

export function Spinner({ className = '' }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className}`} />
}
