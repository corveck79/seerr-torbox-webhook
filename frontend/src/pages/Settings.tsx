import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api';
import { usePlugins } from '../hooks/usePlugins';
import PluginSettingsCard from '../components/PluginSettingsCard';

export default function Settings() {
  const { plugins } = usePlugins();

  return (
    <div className="space-y-6">
      <ChangePasswordCard />

      <div>
        <h1 className="text-xl font-bold mb-1">Plugins</h1>
        <p className="text-muted text-sm">Enable features and connect accounts for your profile.</p>
      </div>

      {plugins.length === 0 && (
        <div className="bg-card rounded-lg border border-border p-6 text-muted text-sm">
          No plugins loaded.
        </div>
      )}

      {plugins.map(plugin => (
        <PluginCard key={plugin.name} plugin={plugin} />
      ))}
    </div>
  );
}

function PluginCard({ plugin }: { plugin: ReturnType<typeof usePlugins>['plugins'][number] }) {
  const hasFields = plugin.user_fields?.length > 0;
  const hasUi = !!plugin.settings_ui;

  return (
    <div className="bg-card rounded-lg border border-border p-6 space-y-4">
      <div>
        <h2 className="text-base font-bold leading-tight">{plugin.label}</h2>
        {plugin.description && (
          <p className="text-muted text-xs mt-0.5">{plugin.description}</p>
        )}
      </div>

      {hasFields && <PluginUserFieldsSection plugin={plugin} />}
      {hasUi && <PluginSettingsCard plugin={plugin} embedded />}
    </div>
  );
}

function PluginUserFieldsSection({ plugin }: { plugin: ReturnType<typeof usePlugins>['plugins'][number] }) {
  const qc = useQueryClient();
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const mutation = useMutation({
    mutationFn: (fields: Record<string, boolean>) => api.setPluginFields(fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['session'] }),
  });

  return (
    <div className="flex flex-wrap gap-4">
      {plugin.user_fields.map(field => {
        const label = plugin.user_field_labels?.[field] || field;
        const value = !!(session?.user as any)?.[field];
        return (
          <label key={field} className="flex items-center gap-2 cursor-pointer select-none">
            <span className="text-sm text-muted">{label}</span>
            <button
              type="button"
              role="switch"
              aria-checked={value}
              onClick={() => mutation.mutate({ [field]: !value })}
              disabled={mutation.isPending}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                ${value ? 'bg-accent' : 'bg-zinc-600'}
                ${mutation.isPending ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform
                ${value ? 'translate-x-4' : 'translate-x-1'}`} />
            </button>
            <span className={`text-xs font-medium ${value ? 'text-accent' : 'text-muted'}`}>
              {value ? 'On' : 'Off'}
            </span>
          </label>
        );
      })}
    </div>
  );
}

function ChangePasswordCard() {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const mutation = useMutation({
    mutationFn: () => api.changePassword(current, password),
    onSuccess: () => {
      setSuccess(true);
      setCurrent(''); setPassword(''); setConfirm('');
      setTimeout(() => setSuccess(false), 3000);
    },
    onError: (e: any) => setError(e.message || 'Failed to change password'),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) { setError('At least 6 characters required'); return; }
    if (password !== confirm) { setError('Passwords do not match'); return; }
    mutation.mutate();
  };

  return (
    <div className="bg-card rounded-lg border border-border p-6">
      <h2 className="text-base font-bold mb-4">Change password</h2>
      {success && <p className="text-ok text-sm mb-3">Password changed successfully.</p>}
      <form onSubmit={submit} className="space-y-3 max-w-sm">
        <div>
          <label className="block text-xs text-muted mb-1">Current password</label>
          <input type="password" value={current} onChange={e => setCurrent(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">New password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Confirm new password</label>
          <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        {error && <p className="text-danger text-xs">{error}</p>}
        <button type="submit" disabled={mutation.isPending}
          className="px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 disabled:opacity-60 font-semibold text-sm">
          {mutation.isPending ? 'Saving...' : 'Change password'}
        </button>
      </form>
    </div>
  );
}
