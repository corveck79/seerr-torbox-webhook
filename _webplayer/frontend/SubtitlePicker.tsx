// Parked — imported only by PlayerModal.tsx

import { useQuery } from '@tanstack/react-query'

interface Sub { language: string; label: string; url: string }

interface Props {
  token:    string
  onSelect: (url: string | null) => void
}

export function SubtitlePicker({ token, onSelect }: Props) {
  const { data } = useQuery<{ subtitles: Sub[] }>({
    queryKey: ['subtitles', token],
    queryFn:  () => fetch(`/stream/${token}/subtitles`).then(r => r.json()),
    enabled:  !!token,
  })

  const subs = data?.subtitles ?? []
  if (!subs.length) return null

  return (
    <select
      onChange={e => onSelect(e.target.value || null)}
      className="bg-zinc-800 text-zinc-300 rounded px-2 py-0.5 text-xs">
      <option value="">💬 Geen ondertitels</option>
      {subs.map(s => (
        <option key={s.url} value={s.url}>
          💬 {s.language.toUpperCase()}{s.label ? ` — ${s.label}` : ''}
        </option>
      ))}
    </select>
  )
}
