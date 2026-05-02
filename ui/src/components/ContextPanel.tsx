// ContextPanel.tsx — UI-DS-06 : McpStatusBar déplacée en bas (margin-top: auto)
import { useState } from 'react';
import { useContextStore } from '../stores/contextStore';
import { McpStatusBar }    from './McpStatusBar';
import { FileTree }        from './FileTree';
import { SpecCard }        from './SpecCard';
import { SpecDetailModal } from './SpecDetailModal';
import { TxCard }          from './TxCard';
import { FileViewModal }   from './FileViewModal';
import { TelemetryPanel }  from './TelemetryPanel'; // V9-09

// ─── Section Workspace ─────────────────────────────────────────────────────────
function WorkspaceSection({ onFileClick }: { onFileClick: (p: string) => void }) {
  const { workspaceFiles, refreshWorkspace } = useContextStore();

  return (
    <section className="context-section">
      <div className="context-section-header">
        <h3>📂 Workspace ({workspaceFiles.length})</h3>
        <button
          className="context-refresh-btn"
          onClick={() => refreshWorkspace().catch(() => {})}
          aria-label="Rafraîchir le workspace"
          title="Rafraîchir"
        >
          ⟳
        </button>
      </div>
      <div className="context-section-body">
        <FileTree onFileClick={onFileClick} />
      </div>
    </section>
  );
}

// ─── Section Specs ─────────────────────────────────────────────────────────────
function SpecsSection({ onSpecClick }: { onSpecClick: (id: string) => void }) {
  const { activeSpecs, refreshSpecs } = useContextStore();

  return (
    <section className="context-section">
      <div className="context-section-header">
        <h3>📋 Specs ({activeSpecs.length})</h3>
        <button
          className="context-refresh-btn"
          onClick={() => refreshSpecs().catch(() => {})}
          aria-label="Rafraîchir les specs"
          title="Rafraîchir"
        >
          ⟳
        </button>
      </div>
      <div className="context-section-body">
        {activeSpecs.length === 0
          ? <p className="context-empty">Aucune spec en mémoire</p>
          : activeSpecs.map(spec => (
              <SpecCard
                key={spec.specId}
                spec={spec}
                onClick={() => onSpecClick(spec.specId)}
              />
            ))
        }
      </div>
    </section>
  );
}

// ─── Section Transactions ──────────────────────────────────────────────────────
function TxSection() {
  const { recentTx } = useContextStore();

  return (
    <section className="context-section">
      <div className="context-section-header">
        <h3>🔄 Transactions ({recentTx.length})</h3>
      </div>
      <div className="context-section-body">
        {recentTx.length === 0
          ? <p className="context-empty">Aucune transaction récente</p>
          : recentTx.slice(0, 10).map(tx => (
              <TxCard key={tx.txId} tx={tx} />
            ))
        }
      </div>
    </section>
  );
}

// ─── ContextPanel ──────────────────────────────────────────────────────────────
export function ContextPanel() {
  const [specModalId,   setSpecModalId]   = useState<string | null>(null);
  const [fileModalPath, setFileModalPath] = useState<string | null>(null);

  return (
    <aside className="context-panel" aria-label="Panneau contexte">
      <WorkspaceSection onFileClick={setFileModalPath} />
      <SpecsSection     onSpecClick={setSpecModalId} />
      <TxSection />
      <TelemetryPanel /> {/* V9-09 : graphe tok/s */}

      {/* MCP bar en bas — UI-DS-06 : .context-mcp-bottom pousse via margin-top auto */}
      <div className="context-mcp-bottom">
        <McpStatusBar />
      </div>

      {specModalId && (
        <SpecDetailModal
          specId={specModalId}
          onClose={() => setSpecModalId(null)}
        />
      )}
      {fileModalPath && (
        <FileViewModal
          filePath={fileModalPath}
          onClose={() => setFileModalPath(null)}
        />
      )}
    </aside>
  );
}
