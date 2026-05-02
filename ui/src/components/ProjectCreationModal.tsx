// ProjectCreationModal.tsx — PROJ-05 + PROJ-UI-04
// Champs : Nom (requis) + Description + Tags (chips) + StorageMode + bouton Inspiration
// Fermeture : Escape / clic overlay / bouton Annuler

import { useState, useEffect, useRef, KeyboardEvent } from 'react';

interface ProjectCreationModalProps {
  onConfirm:           (name: string, description: string, tags: string[], storageMode: string) => Promise<void>;
  onClose:             () => void;
  loading?:            boolean;
  /** PROJ-UI-02 : pré-remplissage depuis InspirationPanel */
  initialName?:        string;
  initialDescription?: string;
  /** PROJ-UI-04 : tags pré-remplis depuis une IdeaCard */
  initialTags?:        string[];
  /** PROJ-UI-04 : ouvre l'InspirationPanel depuis la modal */
  onOpenInspiration?:  () => void;
}

// ── Chips Tag Input ──────────────────────────────────────────────────────────

function TagInput({ tags, onChange }: { tags: string[]; onChange: (t: string[]) => void }) {
  const [input, setInput] = useState('');

  const addTag = (raw: string) => {
    const tag = raw.trim().toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 20);
    if (tag && !tags.includes(tag) && tags.length < 8) {
      onChange([...tags, tag]);
    }
    setInput('');
  };

  const removeTag = (t: string) => onChange(tags.filter(x => x !== t));

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
      e.preventDefault();
      addTag(input);
    } else if (e.key === 'Backspace' && !input && tags.length) {
      removeTag(tags[tags.length - 1]);
    }
  };

  return (
    <div
      style={{
        display:     'flex',
        flexWrap:    'wrap',
        gap:         6,
        padding:     '6px 10px',
        background:  'var(--bg-input)',
        border:      '1px solid var(--border)',
        borderRadius: 6,
        minHeight:   38,
        cursor:      'text',
        alignItems:  'center',
      }}
      onClick={() => { (document.getElementById('tag-chip-input') as HTMLInputElement)?.focus(); }}
    >
      {tags.map(t => (
        <span
          key={t}
          style={{
            display:      'inline-flex',
            alignItems:   'center',
            gap:          4,
            padding:      '2px 8px',
            background:   'var(--accent-dim)',
            border:       '1px solid var(--b-acc)',
            borderRadius: 20,
            fontSize:     11,
            color:        'var(--accent)',
            fontFamily:   'var(--font-mono)',
            fontWeight:   600,
            whiteSpace:   'nowrap',
          }}
        >
          #{t}
          <button
            onClick={e => { e.stopPropagation(); removeTag(t); }}
            style={{
              background: 'none',
              border:     'none',
              color:      'var(--accent)',
              cursor:     'pointer',
              padding:    0,
              lineHeight: 1,
              fontSize:   12,
              opacity:    0.7,
            }}
          >×</button>
        </span>
      ))}
      <input
        id="tag-chip-input"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={() => { if (input.trim()) addTag(input); }}
        placeholder={tags.length === 0 ? 'python, cli, ia… (Entrée pour valider)' : ''}
        maxLength={22}
        style={{
          background:  'transparent',
          border:      'none',
          outline:     'none',
          color:       'var(--text-primary)',
          fontSize:    12,
          fontFamily:  'inherit',
          flexGrow:    1,
          minWidth:    80,
          padding:     '2px 0',
        }}
      />
    </div>
  );
}

// ── StorageMode toggle ────────────────────────────────────────────────────────

function StorageModeToggle({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const modes = [
    { key: 'shared',   label: 'Partagé',  desc: 'Palace ChromaDB global (défaut)' },
    { key: 'isolated', label: 'Isolé',    desc: 'Palace dédié dans le projet' },
  ];
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      {modes.map(m => (
        <button
          key={m.key}
          onClick={() => onChange(m.key)}
          title={m.desc}
          style={{
            flex:        1,
            padding:     '7px 10px',
            background:  value === m.key ? 'var(--accent-dim)' : 'var(--bg-input)',
            border:      `1px solid ${value === m.key ? 'var(--b-acc)' : 'var(--border)'}`,
            borderRadius: 6,
            color:       value === m.key ? 'var(--accent)' : 'var(--text-secondary)',
            fontSize:    12,
            fontWeight:  value === m.key ? 700 : 400,
            cursor:      'pointer',
            transition:  'all 0.15s',
            textAlign:   'center',
          }}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

// ── Composant principal ───────────────────────────────────────────────────────

export function ProjectCreationModal({
  onConfirm,
  onClose,
  loading = false,
  initialName = '',
  initialDescription = '',
  initialTags = [],
  onOpenInspiration,
}: ProjectCreationModalProps) {
  const [name,        setName]        = useState(initialName);
  const [desc,        setDesc]        = useState(initialDescription);
  const [tags,        setTags]        = useState<string[]>(initialTags);
  const [storageMode, setStorageMode] = useState('shared');
  const [error,       setError]       = useState<string | null>(null);
  const nameRef                       = useRef<HTMLInputElement>(null);

  // Sync si pré-remplissage externe change (depuis InspirationPanel)
  useEffect(() => { setName(initialName); },        [initialName]);
  useEffect(() => { setDesc(initialDescription); }, [initialDescription]);
  useEffect(() => { setTags(initialTags); },        [initialTags]);

  // Focus auto à l'ouverture
  useEffect(() => { nameRef.current?.focus(); }, []);

  // Fermeture via Escape
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSubmit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Le nom du projet est requis.');
      nameRef.current?.focus();
      return;
    }
    if (trimmed.length < 2) {
      setError('Le nom doit contenir au moins 2 caractères.');
      return;
    }
    setError(null);
    await onConfirm(trimmed, desc.trim(), tags, storageMode);
  };

  return (
    /* Overlay */
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position:       'fixed',
        inset:          0,
        background:     'rgba(0,0,0,0.6)',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        zIndex:         1000,
        backdropFilter: 'blur(4px)',
      }}
    >
      {/* Boîte modale */}
      <div
        style={{
          width:         440,
          maxHeight:     '90vh',
          overflowY:     'auto',
          background:    'var(--bg-elevated)',
          border:        '1px solid var(--border-strong)',
          borderRadius:  12,
          boxShadow:     'var(--shadow-xl)',
          padding:       '24px 28px',
          display:       'flex',
          flexDirection: 'column',
          gap:           16,
        }}
      >
        {/* ── Titre + bouton Inspiration ── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
            Nouveau projet
          </h3>
          {onOpenInspiration && (
            <button
              onClick={() => { onClose(); onOpenInspiration(); }}
              title="Générer des idées avec l'IA"
              style={{
                display:    'flex',
                alignItems: 'center',
                gap:        5,
                padding:    '5px 11px',
                background: 'var(--accent-dim)',
                border:     '1px solid var(--b-acc)',
                borderRadius: 20,
                color:      'var(--accent)',
                fontSize:   11,
                fontWeight: 600,
                cursor:     'pointer',
                transition: 'opacity 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.opacity = '0.8'; }}
              onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
            >
              💡 Inspiration
            </button>
          )}
        </div>

        {/* ── Champ nom ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Nom <span style={{ color: 'var(--error)', marginLeft: 2 }}>*</span>
          </label>
          <input
            ref={nameRef}
            value={name}
            onChange={e => { setName(e.target.value); setError(null); }}
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit(); }}
            placeholder="ex: Refactor auth module"
            maxLength={80}
            disabled={loading}
            style={{
              padding:     '8px 12px',
              background:  'var(--bg-input)',
              border:      `1px solid ${error ? 'var(--error)' : 'var(--border)'}`,
              borderRadius: 6,
              color:       'var(--text-primary)',
              fontSize:    13,
              outline:     'none',
              transition:  'border-color 0.15s',
            }}
            onFocus={e => { e.currentTarget.style.borderColor = 'var(--border-focus)'; }}
            onBlur={e => { e.currentTarget.style.borderColor = error ? 'var(--error)' : 'var(--border)'; }}
          />
          {error && (
            <span style={{ fontSize: 11, color: 'var(--error)' }}>{error}</span>
          )}
        </div>

        {/* ── Champ description ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Description
            <span style={{ color: 'var(--text-muted)', marginLeft: 6, fontWeight: 400 }}>(optionnel)</span>
          </label>
          <textarea
            value={desc}
            onChange={e => setDesc(e.target.value)}
            placeholder="Décris l'objectif du projet…"
            maxLength={300}
            rows={3}
            disabled={loading}
            style={{
              padding:    '8px 12px',
              background: 'var(--bg-input)',
              border:     '1px solid var(--border)',
              borderRadius: 6,
              color:      'var(--text-primary)',
              fontSize:   13,
              resize:     'vertical',
              fontFamily: 'inherit',
              outline:    'none',
              lineHeight: 1.5,
            }}
            onFocus={e => { e.currentTarget.style.borderColor = 'var(--border-focus)'; }}
            onBlur={e => { e.currentTarget.style.borderColor = 'var(--border)'; }}
          />
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textAlign: 'right' }}>
            {desc.length}/300
          </span>
        </div>

        {/* ── Tags ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Tags
            <span style={{ color: 'var(--text-muted)', marginLeft: 6, fontWeight: 400 }}>
              (optionnel · max 8 · Entrée ou virgule pour valider)
            </span>
          </label>
          <TagInput tags={tags} onChange={setTags} />
        </div>

        {/* ── Storage mode ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>
            Stockage mémoire
          </label>
          <StorageModeToggle value={storageMode} onChange={setStorageMode} />
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {storageMode === 'isolated'
              ? 'Palace ChromaDB dédié — recommandé pour les projets sensibles.'
              : 'Palace ChromaDB partagé — économe en ressources (défaut).'}
          </span>
        </div>

        {/* ── Boutons ── */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
          <button
            onClick={onClose}
            disabled={loading}
            style={{
              padding:    '7px 16px',
              background: 'transparent',
              border:     '1px solid var(--border)',
              borderRadius: 6,
              color:      'var(--text-secondary)',
              fontSize:   13,
              cursor:     loading ? 'not-allowed' : 'pointer',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => { if (!loading) e.currentTarget.style.borderColor = 'var(--border-strong)'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; }}
          >
            Annuler
          </button>

          <button
            onClick={handleSubmit}
            disabled={loading || !name.trim()}
            style={{
              padding:    '7px 20px',
              background: name.trim() && !loading ? 'var(--accent)' : 'var(--accent-soft)',
              border:     '1px solid transparent',
              borderRadius: 6,
              color:      name.trim() && !loading ? 'var(--text-inverse)' : 'var(--text-muted)',
              fontSize:   13,
              fontWeight: 600,
              cursor:     loading || !name.trim() ? 'not-allowed' : 'pointer',
              transition: 'background 0.15s',
            }}
          >
            {loading ? '…' : 'Créer'}
          </button>
        </div>
      </div>
    </div>
  );
}
