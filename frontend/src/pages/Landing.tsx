import { Link } from 'react-router-dom'
import { ArrowRight, Newspaper, TrendingUp, Swords, Trophy, BarChart3 } from 'lucide-react'
import { recapLeagueSlug } from '../lib/supabase'

const demoPath = `/leagues/${recapLeagueSlug}`

function Feature({ icon: Icon, title, body }: { icon: React.ComponentType<{ className?: string }>; title: string; body: string }) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 h-5 w-5 flex-shrink-0 text-pg-accent" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-white">{title}</p>
        <p className="text-sm text-slate-400">{body}</p>
      </div>
    </div>
  )
}

export function Landing() {
  return (
    <div className="min-h-dvh bg-pg-bg">
      {/* ── Hero ──────────────────────────────────────────────── */}
      <section className="mx-auto max-w-3xl px-4 pb-12 pt-20 text-center md:pt-32">
        <h1 className="text-4xl font-black tracking-tight text-white md:text-6xl">
          Full Court Press
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
          The AI-powered newsroom for your fantasy basketball league.
          Weekly recaps, power rankings, matchup breakdowns, and season stats
          — all written in a real sportswriter's voice, fresh every week during the season.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            to={demoPath}
            className="inline-flex items-center gap-2 rounded-pg-lg bg-pg-accent px-6 py-3 text-sm font-bold text-white transition-opacity hover:opacity-90"
          >
            See the demo <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
          <Link
            to="/login"
            className="inline-flex items-center gap-2 rounded-pg-lg border border-pg-border bg-pg-card px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-pg-card-hover"
          >
            Log in
          </Link>
          <Link
            to="/signup"
            className="inline-flex items-center gap-2 rounded-pg-lg border border-pg-border bg-pg-card px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-pg-card-hover"
          >
            Sign up
          </Link>
        </div>
      </section>

      {/* ── Features ──────────────────────────────────────────── */}
      <section className="mx-auto max-w-3xl px-4 pb-16">
        <p className="mb-8 text-center text-xs font-bold uppercase tracking-[0.2em] text-slate-500">
          What you get
        </p>
        <div className="grid gap-6 sm:grid-cols-2">
          <Feature
            icon={Newspaper}
            title="Weekly AI recaps"
            body="Your league's own ESPN-style roundup — multi-voice commentary, awards, and storylines, generated fresh every week."
          />
          <Feature
            icon={TrendingUp}
            title="Power rankings"
            body="Per-team blurbs, all-play win rates, and movement tracking — the real composite score that tells you who's actually good."
          />
          <Feature
            icon={Swords}
            title="Live matchup breakdowns"
            body="Per-category scores, win-lean projections, and head-to-head detail for every matchup in your league."
          />
          <Feature
            icon={Trophy}
            title="Awards & season stats"
            body="Blowout of the Week, Team of the Week, and full-season category leaders across every counting stat."
          />
          <Feature
            icon={BarChart3}
            title="Standings"
            body="Week-scoped standings that reflect how the table looked at that point in the season — not just a live snapshot."
          />
        </div>
      </section>

      {/* ── ESPN-only callout ──────────────────────────────────── */}
      <section className="border-t border-pg-border">
        <div className="mx-auto max-w-3xl px-4 py-10 text-center">
          <p className="text-sm font-semibold text-slate-400">
            ESPN leagues only — Yahoo & Sleeper coming soon.
          </p>
          <p className="mt-2 text-sm text-slate-500">
            Already running an ESPN fantasy basketball league?{' '}
            <Link to={demoPath} className="font-semibold text-pg-accent hover:underline">
              Browse the demo league
            </Link>{' '}
            to see how it works.
          </p>
        </div>
      </section>
    </div>
  )
}
