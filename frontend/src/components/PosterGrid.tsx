import type { TmdbItem } from '../types';
import PosterCard from './PosterCard';

export default function PosterGrid({
  items,
  loading,
  onItemClick,
  empty,
}: {
  items: TmdbItem[] | undefined;
  loading?: boolean;
  onItemClick: (item: TmdbItem) => void;
  empty?: string;
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="aspect-[2/3] rounded-lg bg-card border border-border animate-pulse"
          />
        ))}
      </div>
    );
  }
  if (!items || items.length === 0) {
    return <div className="text-muted text-sm py-8 px-2">{empty || 'No results'}</div>;
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
      {items.map((item) => (
        <PosterCard key={`${item.media_type}-${item.tmdb_id}`} item={item} onClick={onItemClick} />
      ))}
    </div>
  );
}
