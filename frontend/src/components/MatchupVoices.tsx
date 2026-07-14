import type { MatchupTakeaway } from '../api'

/**
 * Renders a matchup's three-voice + insight takeaway (Woj / Barkley / Stephen A
 * / Insight). The factual header (who beat whom) is rendered by the caller.
 */
export function MatchupVoices({ takeaway }: { takeaway: MatchupTakeaway }) {
  const rows: Array<{ label: string; text: string; accent: string }> = [
    { label: 'Woj', text: takeaway.woj, accent: 'text-red-300' },
    { label: 'Barkley', text: takeaway.barkley, accent: 'text-red-300' },
    { label: 'Stephen A', text: takeaway.stephen_a, accent: 'text-red-300' },
    { label: 'Insight', text: takeaway.insight, accent: 'text-sky-300' },
  ]
  return (
    <div className="mt-2 space-y-1.5">
      {rows.map(({ label, text, accent }) => (
        <p key={label} className="text-sm leading-relaxed text-slate-300">
          <span className={`font-semibold ${accent}`}>{label}:</span> {text}
        </p>
      ))}
    </div>
  )
}
