import { Newspaper, Swords, TrendingUp, ArrowRightLeft, Trophy, Table2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { getPublishedArchive, getPublishedRecap } from '../api'
import { recapLeagueSlug } from '../lib/supabase'
import { WeeklyRecapTab } from '../components/WeeklyRecapTab'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

interface TabDef {
  id: string
  label: string
  Icon: React.FC<{ className?: string }>
  enabled: boolean
}

const TABS: TabDef[] = [
  { id: 'weekly-recap', label: 'Weekly Recap', Icon: Newspaper, enabled: true },
  { id: 'matchups', label: 'Matchups', Icon: Swords, enabled: false },
  { id: 'power-rankings', label: 'Power Rankings', Icon: TrendingUp, enabled: false },
  { id: 'transactions', label: 'Transactions', Icon: ArrowRightLeft, enabled: false },
  { id: 'awards', label: 'Awards & Stats', Icon: Trophy, enabled: false },
  { id: 'standings', label: 'Standings', Icon: Table2, enabled: false },
]

export function NewsroomLayout() {
  const { slug, season: seasonStr, week: weekStr } = useParams<{
    slug: string
    season: string
    week: string
  }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('weekly-recap')
  const [adminMode, setAdminMode] = useState(false)
  const [archive, setArchive] = useState<{ week: number; headline?: string }[]>([])
  const [leagueName, setLeagueName] = useState('')

  const effectiveSlug = slug || recapLeagueSlug
  const season = seasonStr ? Number(seasonStr) : RECAP_SEASON
  const week = weekStr ? Number(weekStr) : 1

  // Load published weeks for archive navigation
  useEffect(() => {
    let cancelled = false
    getPublishedArchive(effectiveSlug, season)
      .then((weeks) => {
        if (!cancelled) setArchive(weeks)
      })
      .catch(() => {
        if (!cancelled) setArchive([])
      })
    return () => {
      cancelled = true
    }
  }, [effectiveSlug, season])

  // Try to load league name from a published recap
  useEffect(() => {
    if (week > 0 && week <= 22) {
      let cancelled = false
      getPublishedRecap(effectiveSlug, season, week)
        .then((data) => {
          if (!cancelled && data.league?.name) {
            setLeagueName(String(data.league.name))
          }
        })
        .catch(() => {})
      return () => {
        cancelled = true
      }
    }
  }, [effectiveSlug, season, week])

  const handleWeekChange = (newWeek: number) => {
    navigate(`/leagues/${effectiveSlug}/recaps/${season}/${newWeek}`)
  }

  const handleSeasonChange = (newSeason: number) => {
    // Navigate to first available week in that season, or week 1
    navigate(`/leagues/${effectiveSlug}/recaps/${newSeason}/1`)
  }

  return (
    <div className="space-y-5 pb-8">
      {/* Masthead */}
      <header className="flex flex-col gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">
            {leagueName || 'Patriot Games'}
          </p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-white">Newsroom</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Season selector — single-option for now */}
          <select
            value={season}
            onChange={(e) => handleSeasonChange(Number(e.target.value))}
            className="min-h-11 rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm font-semibold text-white"
            aria-label="Season"
          >
            <option value={2026}>2025–26</option>
          </select>

          {/* Week selector — full range in admin mode, published-only otherwise */}
          {!adminMode && archive.length > 0 ? (
            <select
              value={week}
              onChange={(e) => handleWeekChange(Number(e.target.value))}
              className="min-h-11 rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm font-semibold text-white"
              aria-label="Recap week"
            >
              {archive.map((entry) => (
                <option key={entry.week} value={entry.week}>
                  Week {entry.week}
                  {entry.headline ? ` — ${entry.headline.slice(0, 40)}…` : ''}
                </option>
              ))}
            </select>
          ) : (
            <select
              value={week}
              onChange={(e) => handleWeekChange(Number(e.target.value))}
              className="min-h-11 rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm font-semibold text-white"
              aria-label="Recap week"
            >
              {Array.from({ length: 22 }, (_, i) => i + 1).map((w) => (
                <option key={w} value={w}>
                  Week {w}
                  {!adminMode && archive.some((e) => e.week === w) ? '' : ''}
                </option>
              ))}
            </select>
          )}

          {/* Admin mode toggle — shell level */}
          <button
            type="button"
            onClick={() => setAdminMode((v) => !v)}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-semibold ${
              adminMode
                ? 'border-amber-500 bg-amber-500/15 text-amber-200'
                : 'border-slate-700 bg-slate-900 text-slate-300'
            }`}
          >
            <ShieldCheck className="h-4 w-4" />
            {adminMode ? 'Exit admin mode' : 'Admin mode'}
          </button>
        </div>
      </header>

      {/* Tab bar */}
      <nav className="flex gap-1 overflow-x-auto border-b border-slate-800 pb-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            disabled={!tab.enabled}
            onClick={() => tab.enabled && setActiveTab(tab.id)}
            className={`inline-flex items-center gap-2 whitespace-nowrap rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
              activeTab === tab.id
                ? 'border-b-2 border-red-500 bg-slate-800/50 text-white'
                : tab.enabled
                  ? 'text-slate-400 hover:text-white'
                  : 'cursor-not-allowed text-slate-600'
            }`}
          >
            <tab.Icon className="h-4 w-4" />
            {tab.label}
            {!tab.enabled && (
              <span className="text-[10px] uppercase text-slate-600">Soon</span>
            )}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      {activeTab === 'weekly-recap' && (
        <WeeklyRecapTab slug={effectiveSlug} season={season} week={week} adminMode={adminMode} />
      )}
      {activeTab !== 'weekly-recap' && (
        <div className="flex min-h-[200px] items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-8">
          <p className="text-center text-slate-500">
            <span className="block text-lg font-semibold">Coming soon</span>
            <span className="mt-1 block text-sm">
              {TABS.find((t) => t.id === activeTab)?.label} will be available in a future update.
            </span>
          </p>
        </div>
      )}
    </div>
  )
}
