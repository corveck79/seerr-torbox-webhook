import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, NL_PROVIDER_IDS, tmdbImg } from '../api';
import type { MediaType, TmdbItem } from '../types';
import PosterGrid from '../components/PosterGrid';
import DetailModal from '../components/DetailModal';
import SectionHeader from '../components/SectionHeader';

type Cat =
  | { kind: 'all'; window: 'day' | 'week' }
  | { kind: 'popular'; type: MediaType }
  | { kind: 'now' }
  | { kind: 'upcoming' }
  | { kind: 'top'; type: MediaType }
  | { kind: 'provider'; id: number };

export default function Discover() {
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);

  const open = (item: TmdbItem) => setDetail({ id: item.tmdb_id, type: item.media_type });
  const close = () => setDetail(null);

  return (
    <div className="space-y-8">
      <ProviderStrip onPick={(pid) => setDetail(null)} />

      <Row
        title="🔥 Trending this week"
        query={['trending', 'all', 'week']}
        fetcher={() => api.trending('all', 'week').then((r) => r.results)}
        toggles={[
          { label: 'Today', queryKey: ['trending', 'all', 'day'], fetcher: () => api.trending('all', 'day').then((r) => r.results) },
          { label: 'Week', queryKey: ['trending', 'all', 'week'], fetcher: () => api.trending('all', 'week').then((r) => r.results) },
        ]}
        onItemClick={open}
      />

      <Row
        title="⭐ Popular movies"
        query={['popular', 'movie']}
        fetcher={() => api.popular('movie').then((r) => r.results)}
        toggles={[
          { label: 'Movies', queryKey: ['popular', 'movie'], fetcher: () => api.popular('movie').then((r) => r.results) },
          { label: 'TV', queryKey: ['popular', 'tv'], fetcher: () => api.popular('tv').then((r) => r.results) },
        ]}
        onItemClick={open}
      />

      <Row
        title="🎬 Now playing in theaters"
        query={['now-playing']}
        fetcher={() => api.nowPlaying().then((r) => r.results)}
        onItemClick={open}
      />

      <Row
        title="📅 Upcoming"
        query={['upcoming']}
        fetcher={() => api.upcoming().then((r) => r.results)}
        onItemClick={open}
      />

      <Row
        title="🏆 Top rated"
        query={['top-rated', 'movie']}
        fetcher={() => api.topRated('movie').then((r) => r.results)}
        toggles={[
          { label: 'Movies', queryKey: ['top-rated', 'movie'], fetcher: () => api.topRated('movie').then((r) => r.results) },
          { label: 'TV', queryKey: ['top-rated', 'tv'], fetcher: () => api.topRated('tv').then((r) => r.results) },
        ]}
        onItemClick={open}
      />

      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={close}
        onSelectItem={open}
      />
    </div>
  );
}

interface ToggleSpec {
  label: string;
  queryKey: readonly unknown[];
  fetcher: () => Promise<TmdbItem[]>;
}

function Row({
  title,
  query,
  fetcher,
  toggles,
  onItemClick,
}: {
  title: string;
  query: readonly unknown[];
  fetcher: () => Promise<TmdbItem[]>;
  toggles?: ToggleSpec[];
  onItemClick: (item: TmdbItem) => void;
}) {
  const [active, setActive] = useState<{ key: readonly unknown[]; fn: () => Promise<TmdbItem[]> }>(
    { key: query, fn: fetcher },
  );
  const { data, isLoading } = useQuery({ queryKey: active.key as any[], queryFn: active.fn });

  return (
    <section>
      <SectionHeader
        title={title}
        action={
          toggles &&
          toggles.map((t) => (
            <button
              key={t.label}
              type="button"
              onClick={() => setActive({ key: t.queryKey, fn: t.fetcher })}
              className={`text-xs px-3 py-1 rounded border ${
                JSON.stringify(active.key) === JSON.stringify(t.queryKey)
                  ? 'border-accent bg-accent/10 text-white'
                  : 'border-border text-muted hover:text-white'
              }`}
            >
              {t.label}
            </button>
          ))
        }
      />
      <PosterGrid items={data} loading={isLoading} onItemClick={onItemClick} />
    </section>
  );
}

function ProviderStrip({ onPick }: { onPick: (pid: number | null) => void }) {
  const [activePid, setActivePid] = useState<number | null>(null);
  const { data: providers } = useQuery({
    queryKey: ['providers', 'movie'],
    queryFn: () => api.providers('movie'),
  });
  const { data: providerItems, isLoading: filtLoading } = useQuery({
    queryKey: ['by-provider', activePid],
    queryFn: () => (activePid ? api.byProvider('movie', activePid).then((r) => r.results) : Promise.resolve([])),
    enabled: !!activePid,
  });
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);

  const wanted = Object.values(NL_PROVIDER_IDS);
  const visible = (providers?.providers || [])
    .filter((p) => wanted.includes(p.id as any))
    .sort((a, b) => wanted.indexOf(a.id as any) - wanted.indexOf(b.id as any));

  return (
    <section>
      <div className="flex gap-2 overflow-x-auto scrollbar-hidden pb-2 -mx-1 px-1">
        <ProviderChip
          name="All"
          active={activePid === null}
          onClick={() => {
            setActivePid(null);
            onPick(null);
          }}
        />
        {visible.map((p) => (
          <ProviderChip
            key={p.id}
            name={p.name}
            logo={tmdbImg.logo(p.logo_path)}
            active={activePid === p.id}
            onClick={() => {
              setActivePid(p.id);
              onPick(p.id);
            }}
          />
        ))}
      </div>
      {activePid !== null && (
        <div className="mt-4">
          <SectionHeader title="Available on this service" subtitle="Most popular for streaming in NL" />
          <PosterGrid
            items={providerItems}
            loading={filtLoading}
            onItemClick={(it) => setDetail({ id: it.tmdb_id, type: it.media_type })}
          />
        </div>
      )}
      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={() => setDetail(null)}
        onSelectItem={(it) => setDetail({ id: it.tmdb_id, type: it.media_type })}
      />
    </section>
  );
}

function ProviderChip({
  name,
  logo,
  active,
  onClick,
}: {
  name: string;
  logo?: string | null;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-full text-xs whitespace-nowrap
                   border transition ${
                     active
                       ? 'bg-accent text-white border-accent'
                       : 'bg-card text-white border-border hover:border-accent/50'
                   }`}
    >
      {logo && <img src={logo} alt="" className="w-5 h-5 rounded" />}
      <span>{name}</span>
    </button>
  );
}
