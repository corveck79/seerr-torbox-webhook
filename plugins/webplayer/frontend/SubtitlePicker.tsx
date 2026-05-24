import { useQuery } from '@tanstack/react-query'

interface Sub { language: string; label: string; url: string }

export default function SubtitlePicker({ token, onSelect }: {
  token:    string
  onSelect: (url: string | null) => void
}) {
  const { data } = useQuery<{ subtitles: Sub[] }>({
    queryKey: ['subtitles', token],
    queryFn:  () => fetch(`/stream/${token}/subtitles`).then(r => r.json()),
    enabled:  !!token,
    refetchInterval: q => (q.state.data?.subtitles?.length ? false : 3000),
  })

  const subs = data?.subtitles ?? []
  if (!subs.length) return null

  return (
    <select
      onChange={e => onSelect(e.target.value || null)}
      className="bg-zinc-800 text-zinc-300 rounded px-2 py-0.5"
    >
      <option value="">💬 Geen ondertitels</option>
      {subs.map(s => (
        <option key={s.url} value={s.url}>
          💬 {s.language.toUpperCase()}{s.label ? ` — ${s.label}` : ''}
        </option>
      ))}
    </select>
  )
}
