import type { TxBadge, SpecBadge } from '../types/chat';

/**
 * Détecte un pattern TX dans la réponse assistant.
 * Format : "TX: tx_xxxx | Fichiers: a.py, b.py | ✅"
 */
export function extractTxBadge(text: string): TxBadge | null {
  const m = text.match(
    /TX:\s*(tx_[\w]{1,20})\s*\|\s*Fichiers?:\s*([^|]+?)\s*\|\s*(✅|↩|⚠)/
  );
  if (!m) return null;
  return {
    txId:      m[1],
    files:     m[2].split(',').map(f => f.trim()).filter(Boolean),
    status:    m[3] === '✅' ? 'committed' : m[3] === '↩' ? 'rolled_back' : 'partial',
    timestamp: new Date().toISOString(),
  };
}

/**
 * Détecte un pattern SpecBadge dans la réponse.
 * Format : SPEC_GENERATED: specId=xxx title="yyy yyy" domain=zzz validated=true score=0.92 autoStored=true
 * Le titre est entouré de guillemets pour supporter les espaces (fix [object Object]).
 * autoStored est optionnel (absent dans les réponses antérieures à CTX-04).
 */
export function extractSpecBadge(text: string): SpecBadge | null {
  // Format actuel : title="..." (guillemets, supporte les espaces)
  const m = text.match(
    /SPEC_GENERATED:\s*specId=([\w]+)\s+title="([^"]+)"\s+domain=(\w+)\s+validated=(true|false)\s+score=([\d.]+)(?:\s+autoStored=(true|false))?/
  );
  if (m) {
    return {
      specId:     m[1],
      title:      m[2].trim(),
      domain:     m[3],
      validated:  m[4] === 'true',
      score:      parseFloat(m[5]),
      autoStored: m[6] === 'true',
    };
  }
  // Fallback : ancien format sans guillemets (rétro-compat messages persistés)
  const mLegacy = text.match(
    /SPEC_GENERATED:\s*specId=([\w]+)\s+title=([^\s]+)\s+domain=(\w+)\s+validated=(true|false)\s+score=([\d.]+)(?:\s+autoStored=(true|false))?/
  );
  if (!mLegacy) return null;
  return {
    specId:     mLegacy[1],
    title:      mLegacy[2].trim(),
    domain:     mLegacy[3],
    validated:  mLegacy[4] === 'true',
    score:      parseFloat(mLegacy[5]),
    autoStored: mLegacy[6] === 'true',
  };
}
