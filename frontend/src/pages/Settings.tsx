import { usePlugins } from '../hooks/usePlugins';
import PluginSettingsCard from '../components/PluginSettingsCard';

export default function Settings() {
  const { plugins } = usePlugins();
  const pluginsWithUi = plugins.filter(p => p.settings_ui);

  return (
    <div className="space-y-6">
      <div className="bg-card rounded-lg border border-border p-6">
        <h2 className="text-lg font-bold mb-2">Settings</h2>
        <p className="text-muted text-sm mb-4">
          Runtime settings are managed in the admin panel.
        </p>
        <a
          href="/admin#settings"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-sm font-semibold"
        >
          Open Settings
        </a>
      </div>

      {pluginsWithUi.map(plugin => (
        <PluginSettingsCard key={plugin.name} plugin={plugin} />
      ))}
    </div>
  );
}
