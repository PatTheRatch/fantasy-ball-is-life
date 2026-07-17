import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'

const ESPN_RED = '#e03131'
const markdownComponents: Components = {
  h1: (props) => (
    <h1
      className="mb-2 text-xl font-bold text-white"
      {...props}
    />
  ),
  h2: (props) => (
    <h2
      className="mb-2 text-lg font-bold text-white"
      {...props}
    />
  ),
  h3: (props) => (
    <h3
      className="mb-1.5 text-base font-bold text-white"
      {...props}
    />
  ),
  p: (props) => (
    <p className="leading-normal text-[#8b949e]" {...props} />
  ),
  strong: (props) => (
    <strong
      className="font-semibold"
      style={{ color: ESPN_RED }}
      {...props}
    />
  ),
  em: (props) => (
    <em className="italic text-slate-400" {...props} />
  ),
  ul: (props) => (
    <ul
      className="my-2 list-disc pl-5 text-[#8b949e] marker:text-[#e03131]"
      {...props}
    />
  ),
  ol: (props) => (
    <ol className="my-2 list-decimal pl-5 text-[#8b949e]" {...props} />
  ),
  li: (props) => (
    <li className="text-[#8b949e]" {...props} />
  ),
}

export function AiCommentaryCard({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)
  const [needsToggle, setNeedsToggle] = useState(false)

  useEffect(() => {
    const el = bodyRef.current
    if (!el || expanded) return
    const id = requestAnimationFrame(() => {
      setNeedsToggle(el.scrollHeight > el.clientHeight + 1)
    })
    return () => cancelAnimationFrame(id)
  }, [text, expanded])

  return (
    <div
      className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-3 text-sm leading-relaxed"
      style={{ borderLeftWidth: 3, borderLeftColor: ESPN_RED }}
    >
      <div
        ref={bodyRef}
        className={
          expanded
            ? '[&_p+p]:mt-2 [&_li+p]:mt-2'
            : 'line-clamp-4 [&_p+p]:mt-2 [&_li+p]:mt-2'
        }
      >
        <ReactMarkdown components={markdownComponents}>{text}</ReactMarkdown>
      </div>
      {(expanded || needsToggle) && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-2 text-xs font-semibold text-pg-accent"
        >
          {expanded ? 'Show less' : 'Read more'}
        </button>
      )}
    </div>
  )
}
