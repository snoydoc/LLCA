import { useCallback, useRef } from 'react';

/**
 * Hook streaming simulé — découplé de ChatPanel pour être réutilisable.
 * Retourne une fonction `stream(text, msgId, appendToken)` qui émet
 * les tokens avec le délai configuré, et peut être annulée.
 */
export function useStreaming(delayMs: number) {
  const cancelRef = useRef(false);

  const stream = useCallback(async (
    text:        string,
    msgId:       string,
    appendToken: (id: string, token: string) => void,
  ): Promise<void> => {
    cancelRef.current = false;
    const tokens = text.match(/\S+\s*/g) ?? [text];

    for (const token of tokens) {
      if (cancelRef.current) break;
      appendToken(msgId, token);
      if (delayMs > 0) {
        await new Promise(r => setTimeout(r, delayMs));
      }
    }
  }, [delayMs]);

  const cancel = useCallback(() => {
    cancelRef.current = true;
  }, []);

  return { stream, cancel };
}
