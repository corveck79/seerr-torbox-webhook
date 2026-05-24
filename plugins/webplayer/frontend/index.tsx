/**
 * Web Player plugin — frontend entry point.
 * Registers UI slots consumed by the core SPA via usePluginSlots().
 * Removing this plugin removes all web player UI automatically.
 */
import PlayerModal from './PlayerModal'

export const slots: Record<string, React.ComponentType<any>> = {
  'episode-player': PlayerModal,
}
