import type { ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Table — editorial and dense variants with shared sorting primitives        */
/* -------------------------------------------------------------------------- */

export type TableVariant = 'editorial' | 'dense'

interface TableProps {
  children: ReactNode
  variant?: TableVariant
  className?: string
}

export function TableRoot({ children, variant = 'editorial', className = '' }: TableProps) {
  return (
    <div
      className={`overflow-x-auto rounded-xl border border-slate-700/60 ${className}`}
    >
      <table
        className={`w-full text-left text-xs ${
          variant === 'dense' ? '[&_td]:py-1 [&_th]:py-1' : '[&_td]:py-2 [&_th]:py-1.5'
        }`}
      >
        {children}
      </table>
    </div>
  )
}

export function TableHead({ children }: { children: ReactNode }) {
  return (
    <thead>
      <tr className="border-b border-slate-700">{children}</tr>
    </thead>
  )
}

export function TableBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>
}

/* -------------------------------------------------------------------------- */
/* Sortable header cell                                                       */
/* -------------------------------------------------------------------------- */

import { ChevronUp, ChevronDown } from 'lucide-react'

export type SortDir = 'asc' | 'desc'

interface SortableThProps {
  col: string
  children: ReactNode
  sort: { col: string; dir: SortDir }
  onSort: (col: string) => void
  sticky?: boolean
  stickyLeft?: string
  className?: string
}

export function SortableTh({
  col,
  children,
  sort,
  onSort,
  sticky,
  stickyLeft,
  className = '',
}: SortableThProps) {
  const isActive = sort.col === col
  return (
    <th
      className={`cursor-pointer select-none whitespace-nowrap px-2 text-[11px] font-medium text-slate-400 hover:text-white ${
        sticky ? 'sticky z-10 bg-slate-900' : ''
      } ${className}`}
      style={stickyLeft ? { left: stickyLeft } : undefined}
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {children}
        {isActive && (
          sort.dir === 'asc'
            ? <ChevronUp className="inline h-3 w-3" />
            : <ChevronDown className="inline h-3 w-3" />
        )}
      </span>
    </th>
  )
}

/* -------------------------------------------------------------------------- */
/* Plain header cell (non-sortable)                                           */
/* -------------------------------------------------------------------------- */

interface ThProps {
  children: ReactNode
  sticky?: boolean
  stickyLeft?: string
  className?: string
}

export function Th({ children, sticky, stickyLeft, className = '' }: ThProps) {
  return (
    <th
      className={`whitespace-nowrap px-2 text-[11px] font-medium text-slate-400 ${sticky ? 'sticky z-10 bg-slate-900' : ''} ${className}`}
      style={stickyLeft ? { left: stickyLeft } : undefined}
    >
      {children}
    </th>
  )
}

/* -------------------------------------------------------------------------- */
/* Data cell                                                                  */
/* -------------------------------------------------------------------------- */

interface TdProps {
  children: ReactNode
  sticky?: boolean
  stickyLeft?: string
  className?: string
}

export function Td({ children, sticky, stickyLeft, className = '' }: TdProps) {
  return (
    <td
      className={`px-2 tabular-nums ${sticky ? 'sticky z-10 bg-slate-900' : 'text-slate-300'} ${className}`}
      style={stickyLeft ? { left: stickyLeft } : undefined}
    >
      {children}
    </td>
  )
}

/* -------------------------------------------------------------------------- */
/* Row (with hover state)                                                     */
/* -------------------------------------------------------------------------- */

interface TrProps {
  children: ReactNode
  className?: string
}

export function Tr({ children, className = '' }: TrProps) {
  return (
    <tr className={`border-b border-slate-800/50 hover:bg-slate-800/30 ${className}`}>
      {children}
    </tr>
  )
}
