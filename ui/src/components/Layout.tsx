import { useSettingsStore } from '../stores/settingsStore';
import { TitleBar }     from './TitleBar';
import { Sidebar }      from './Sidebar';
import { ChatPanel }    from './ChatPanel';
import { ContextPanel } from './ContextPanel';

interface LayoutProps {
  onOpenSettings?: () => void;
  onOpenHelp?:     () => void;
}

export function Layout({ onOpenSettings, onOpenHelp }: LayoutProps) {
  const { panelMode } = useSettingsStore();

  // Grille : Sidebar (52px) | Chat (1fr) | ContextPanel (280px)
  // compact = sans ContextPanel, focus = chat seul sans sidebar
  const gridTemplate =
    panelMode === 'standard' ? '52px 1fr 280px' :
    panelMode === 'compact'  ? '52px 1fr'        :
    /* focus */                '1fr';

  return (
    <div className="app-shell">
      <TitleBar />
      <div
        className="layout"
        style={{ gridTemplateColumns: gridTemplate }}
        data-mode={panelMode}
      >
        {panelMode !== 'focus' && (
          <Sidebar
            onOpenSettings={onOpenSettings}
            onOpenHelp={onOpenHelp}
          />
        )}
        <ChatPanel />
        {panelMode === 'standard' && <ContextPanel />}
      </div>
    </div>
  );
}
