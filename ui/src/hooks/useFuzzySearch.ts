// hooks/useFuzzySearch.ts — Filtrage fuzzy + navigation clavier (REFACTO-UI-01)
// Responsabilité unique : état query, index sélectionné, handler clavier.
// Importé par CommandPalette.tsx.

import { useState, useEffect, useRef } from 'react';

export interface FuzzyItem {
  id: string;
  label: string;
  handler: () => void;
}

export interface UseFuzzySearchReturn<T extends FuzzyItem> {
  query:         string;
  setQuery:      (q: string) => void;
  selectedIndex: number;
  setSelectedIndex: (i: number) => void;
  filtered:      T[];
  inputRef:      React.RefObject<HTMLInputElement>;
  handleKey:     (e: React.KeyboardEvent) => void;
}

export function useFuzzySearch<T extends FuzzyItem>(
  items:   T[],
  onClose: () => void,
): UseFuzzySearchReturn<T> {
  const [query, setQuery]                   = useState('');
  const [selectedIndex, setSelectedIndex]   = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Filtrage insensible à la casse
  const filtered = query.trim()
    ? items.filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
    : items;

  // Reset index quand la query change
  useEffect(() => setSelectedIndex(0), [query]);

  // Focus auto à l'ouverture
  useEffect(() => { inputRef.current?.focus(); }, []);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      if (filtered[selectedIndex]) filtered[selectedIndex].handler();
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  return { query, setQuery, selectedIndex, setSelectedIndex, filtered, inputRef, handleKey };
}
