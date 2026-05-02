// FileTree.tsx — Arbre de fichiers workspace collapsible (Sprint UI-03)
import { useState } from 'react';
import { useContextStore } from '../stores/contextStore';

// ─── Types internes ────────────────────────────────────────────────────────────
type FileNode = { [key: string]: FileNode | null };

function buildTree(files: string[]): FileNode {
  const root: FileNode = {};
  for (const f of files) {
    const parts = f.replace(/\\/g, '/').split('/');
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node[part] || node[part] === null) node[part] = {};
      node = node[part] as FileNode;
    }
    node[parts[parts.length - 1]] = null; // feuille = fichier
  }
  return root;
}

function sortedEntries(node: FileNode): [string, FileNode | null][] {
  const entries = Object.entries(node) as [string, FileNode | null][];
  // Dossiers d'abord, puis fichiers, chacun alphabétique
  return [
    ...entries.filter(([, v]) => v !== null).sort(([a], [b]) => a.localeCompare(b)),
    ...entries.filter(([, v]) => v === null).sort(([a], [b]) => a.localeCompare(b)),
  ];
}

// ─── Nœud récursif ─────────────────────────────────────────────────────────────
interface NodeProps {
  name:          string;
  node:          FileNode | null;
  path:          string;
  depth:         number;
  modifiedFiles: string[];
  onFileClick:   (path: string) => void;
}

function FileTreeNode({ name, node, path, depth, modifiedFiles, onFileClick }: NodeProps) {
  const isDir = node !== null;
  const [expanded, setExpanded] = useState(depth === 0);
  const isModified = !isDir && modifiedFiles.some(f => f.replace(/\\/g, '/').endsWith(path.replace(/\\/g, '/')));

  if (!isDir) {
    return (
      <div
        className={`tree-file${isModified ? ' tree-file-modified' : ''}`}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => onFileClick(path)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onFileClick(path)}
        title={path}
      >
        <span className="tree-file-icon" aria-hidden="true">📄</span>
        <span className="tree-file-name">{name}</span>
        {isModified && (
          <span className="tree-modified-badge" aria-label="Modifié récemment">✏</span>
        )}
      </div>
    );
  }

  return (
    <div className="tree-dir">
      <div
        className="tree-dir-header"
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => setExpanded(e => !e)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && setExpanded(v => !v)}
      >
        <span className="tree-dir-arrow" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
        <span className="tree-dir-icon" aria-hidden="true">📁</span>
        <span className="tree-dir-name">{name}/</span>
      </div>
      {expanded && depth < 3 && sortedEntries(node).map(([k, v]) => (
        <FileTreeNode
          key={k}
          name={k}
          node={v}
          path={`${path}/${k}`}
          depth={depth + 1}
          modifiedFiles={modifiedFiles}
          onFileClick={onFileClick}
        />
      ))}
    </div>
  );
}

// ─── Composant principal ───────────────────────────────────────────────────────
interface FileTreeProps {
  onFileClick: (path: string) => void;
}

export function FileTree({ onFileClick }: FileTreeProps) {
  const { workspaceFiles, modifiedFiles, refreshWorkspace } = useContextStore();

  if (workspaceFiles.length === 0) {
    return (
      <div className="tree-empty">
        <p className="context-empty">Aucun fichier indexé</p>
        <button className="context-refresh-btn" onClick={() => refreshWorkspace().catch(() => {})}>
          ⟳ Rafraîchir
        </button>
      </div>
    );
  }

  const tree = buildTree(workspaceFiles);

  return (
    <div className="file-tree" role="tree" aria-label="Arborescence du workspace">
      {sortedEntries(tree).map(([k, v]) => (
        <FileTreeNode
          key={k}
          name={k}
          node={v}
          path={k}
          depth={0}
          modifiedFiles={modifiedFiles}
          onFileClick={onFileClick}
        />
      ))}
    </div>
  );
}
