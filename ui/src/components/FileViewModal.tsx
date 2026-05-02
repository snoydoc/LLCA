// FileViewModal.tsx — Lecteur de fichier workspace (Sprint UI-03)
import { useEffect, useState, useRef } from 'react';
import { CodeBlock } from './CodeBlock';

interface FileViewModalProps {
  filePath: string;
  onClose:  () => void;
}

function inferLang(path: string): string {
  if (path.endsWith('.py'))   return 'python';
  if (path.endsWith('.ts') || path.endsWith('.tsx')) return 'typescript';
  if (path.endsWith('.js') || path.endsWith('.jsx')) return 'javascript';
  if (path.endsWith('.md'))   return 'markdown';
  if (path.endsWith('.json')) return 'json';
  if (path.endsWith('.yml') || path.endsWith('.yaml')) return 'yaml';
  if (path.endsWith('.css'))  return 'css';
  return '';
}

export function FileViewModal({ filePath, onClose }: FileViewModalProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error,   setError]   = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setContent(null);
    setError(null);
    const lcca = (window as any).lcca;
    if (!lcca?.readWorkspaceFile) {
      setError('API readWorkspaceFile non disponible.');
      return;
    }
    lcca.readWorkspaceFile(filePath)
      .then((c: string) => setContent(c))
      .catch((e: Error) => setError(e.message));
  }, [filePath]);

  // Fermer sur Escape + focus trap minimal
  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    el.addEventListener('keydown', onKey);
    el.focus();
    return () => el.removeEventListener('keydown', onKey);
  }, [onClose]);

  const shortName = filePath.split(/[\\/]/).pop() ?? filePath;

  return (
    <div
      className="modal-overlay"
      onClick={e => e.target === e.currentTarget && onClose()}
      aria-modal="true"
    >
      <div
        className="modal-content file-view-modal"
        role="dialog"
        aria-label={`Fichier ${shortName}`}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="modal-header">
          <h2>📄 {shortName}</h2>
          <span className="modal-filepath">{filePath}</span>
          <button onClick={onClose} aria-label="Fermer" className="modal-close-btn">×</button>
        </div>

        <div className="modal-body file-view-body">
          {!content && !error && (
            <div className="modal-loading" aria-live="polite">Chargement…</div>
          )}
          {error && (
            <div className="modal-error" role="alert">
              Erreur : {error}
            </div>
          )}
          {content !== null && (
            <CodeBlock
              language={inferLang(filePath)}
              code={content}
              filename={filePath}
            />
          )}
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-primary">Fermer</button>
        </div>
      </div>
    </div>
  );
}
