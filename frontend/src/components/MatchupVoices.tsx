import type { MatchupTakeaway } from '../api'

/**
 * Renders a matchup's three-voice + insight takeaway (Woj / Barkley / Stephen A
 * / Insight). The factual header (who beat whom) is rendered by the caller.
 *
 * Defensive by design: only renders the beats that are present, and falls back
 * to a legacy single-`text` blurb, so a pre-reshape stored edition (or any
 * partial data) renders readably instead of crashing.
 */
export function MatchupVoices({
  takeaway,
}: {
  takeaway: MatchupTakeaway & { text?: string }
}) {
  const rows = [
    { label: 'Woj', text: takeaway.woj, accent: 'text-red-300' },
    { label: 'Barkley', text: takeaway.barkley, accent: 'text-red-300' },
    { label: 'Stephen A', text: takeaway.stephen_a, accent: 'text-red-300' },
    { label: 'Insight', text: takeaway.insight, accent: 'text-sky-300' },
  ].filter((row) => Boolean(row.text))

  if (rows.length === 0) {
    // Legacy edition (pre-reshape) carried a single `text` blurb.
    return takeaway.text ? (
      <p className="mt-2 text-sm leading-relaxed text-slate-300">{takeaway.text}</p>
    ) : null
  }

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
