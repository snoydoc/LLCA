// useFocusTrap.ts — Focus trap WCAG 2.1 AA pour les modals (Sprint UI-05)
import { useEffect } from 'react';

const FOCUSABLE_SELECTORS =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(
  ref: React.RefObject<HTMLElement | null>,
  active: boolean
) {
  useEffect(() => {
    if (!active || !ref.current) return;
    const el = ref.current;

    const focusable = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS));
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];

    // Focus auto sur le premier élément interactif
    first?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Tab') return;
      if (focusable.length === 0) { e.preventDefault(); return; }

      if (e.shiftKey) {
        // Shift+Tab : si on est sur le premier → aller au dernier
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        // Tab : si on est sur le dernier → revenir au premier
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }

    el.addEventListener('keydown', onKeyDown);
    return () => el.removeEventListener('keydown', onKeyDown);
  }, [active, ref]);
}
