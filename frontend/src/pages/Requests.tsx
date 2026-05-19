import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export default function Requests() {
  const { data, isLoading } = useQuery({ queryKey: ['my-requests'], queryFn: api.myRequests });
  if (isLoading) return <div className="text-muted">Loading…</div>;
  const items = data?.items || [];
  if (!items.length) {
    return (
      <div className="text-center py-16">
        <div className="text-5xl mb-3">📋</div>
        <h2 className="text-lg font-semibold mb-1">No requests yet</h2>
        <p className="text-muted text-sm">Anything you add from Discover shows up here.</p>
      </div>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-muted uppercase border-b border-border">
        <tr>
          <th className="text-left py-2 px-3">Title</th>
          <th className="text-left py-2 px-3">Type</th>
          <th className="text-left py-2 px-3">Status</th>
          <th className="text-left py-2 px-3">Requested</th>
          <th className="text-left py-2 px-3">Note</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r: any) => (
          <tr key={r.id} className="border-b border-border/50 hover:bg-card">
            <td className="py-2 px-3 font-medium">{r.title}</td>
            <td className="py-2 px-3 text-muted">{r.media_type}</td>
            <td className="py-2 px-3">
              <StatusPill status={r.status} />
            </td>
            <td className="py-2 px-3 text-muted text-xs">{r.created_at}</td>
            <td className="py-2 px-3 text-muted text-xs">{r.note || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StatusPill({ status }: { status: string }) {
  const cls =
    status === 'approved' ? 'bg-ok/20 text-ok' :
    status === 'denied' ? 'bg-red-500/20 text-red-400' :
    'bg-amber/20 text-amber';
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold capitalize ${cls}`}>{status}</span>;
}
