// Parked — exact changes to make in frontend/src/pages/Admin.tsx when activating.

// ── 1. Table header — add column after "Enabled" (line ~100) ──────────────────
//
// Add after <th ...>Enabled</th>:
//   <th className="text-left py-2 px-3">Web Player</th>


// ── 2. Table row — add toggle after the Enabled toggle (line ~115) ────────────
//
// Add after the Enabled <td>:
//   <td className="py-2 px-3">
//     <Toggle
//       on={u.webplayer_enabled}
//       onClick={() => updateMut.mutate({ id: u.id, fields: { webplayer_enabled: !u.webplayer_enabled } })}
//     />
//   </td>


// ── 3. api.ts updateUser fields type — add webplayer_enabled ──────────────────
//
// In api.ts, wherever updateUser fields are typed, add:
//   webplayer_enabled?: boolean


// ── 4. DetailModal.tsx — show Play button only when enabled ───────────────────
//
// In DetailModal.tsx, find where the "In library" button is shown.
// Wrap the Play button with a session check:
//
// const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session })
//
// {session?.user?.webplayer_enabled && libStatus === 'success' && (
//   <button
//     onClick={() => setPlayerOpen(true)}
//     className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500
//                text-white rounded-lg text-sm font-medium transition-colors"
//   >
//     ▶ Afspelen in browser
//   </button>
// )}
//
// {playerOpen && (
//   <PlayerModal
//     imdb_id={detail.imdb_id!}
//     media_type={detail.media_type}
//     title={detail.title}
//     onClose={() => setPlayerOpen(false)}
//   />
// )}
