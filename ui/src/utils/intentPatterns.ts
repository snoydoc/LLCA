// intentPatterns.ts — Tableau PATTERNS de routing heuristique (REFACTO-UI-01)
// Responsabilité unique : définir les patterns NL → outil MCP.
// Importé par router.ts ; ne pas importer directement depuis les composants.

import { inferDomain, extractCode } from './router';
import type { RoutedIntent } from './router';

export interface Pattern {
  test:  (t: string) => boolean;
  route: (t: string) => RoutedIntent;
}

export const PATTERNS: Pattern[] = [
  // @spec <intent> [domain:<domain>]
  {
    test: t => /^@spec\s+/i.test(t),
    route: t => {
      const rest = t.replace(/^@spec\s+/i, '').trim();
      const domainMatch = rest.match(/\bdomain:(\w+)/i);
      const domain = domainMatch?.[1] ?? inferDomain(rest);
      const intent = rest.replace(/\bdomain:\w+/i, '').trim();
      return { tool: 'generate_spec', args: { intent, domain } };
    },
  },

  // NL libre : "créer une spec", "génère des spécifications", "nouvelle spec pour X", etc.
  // SPEC-01 FIX — ces formulations naturelles doivent router vers generate_spec
  {
    test: (t) => {
      const n = t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      return (
        /\b(creer?|generer?|genere?|faire?|produire?|ecrire?|rediger?|definir?|construire?)\b/.test(n) &&
        /\bspec(s|ification)?\b/.test(n)
      ) ||
      /\bnouvelle?\s+spec(s|ification)?\b/i.test(t) ||
      /\bspec(s|ification)?\s+(pour|de|sur|du|d[eu]s?)\b/i.test(t) ||
      /\bsp[eé]cifications?\s+(techniques?|compl[eè]tes?|d[eé]taill[eé]es?|fonctionnelles?)\b/i.test(t);
    },
    route: t => {
      const domain = inferDomain(t);
      return { tool: 'generate_spec', args: { intent: t.trim(), domain } };
    },
  },

  // Coding intent : "code X dans Y", "crée une fonction", "écris un module", "ajoute une classe",
  // "modifie le fichier", "dans le dossier", "implémente", etc.
  // FIX UI-CODE-01 — ces requêtes routaient vers llm_chat (fallback) au lieu d'edit_batch
  {
    test: (t) => {
      const n = t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      // Verbe d'action de codage
      const hasCodeVerb = /\b(cod(e|er?)|impl[eé]ment(e|er?)|creer?|cr[eé]e|[eé]cri(s|re|t)|ajoute?|ajout(e|er?)|modifi(e|er?)|g[eé]n[eè]re?|construi(s|re)|cr[eé]([eé]|er?)|d[eé]velopp(e|er?)|mets?\s+en\s+place)\b/.test(n);
      // Cible fichier / dossier / module
      const hasFileTarget = /\b(fichier|dossier|module|classe|fonction|script|package|r[eé]pertoire|dans\s+[\w\/\.]+|dans\s+le|dans\s+un|dans\s+ce|dans\s+mon|dans\s+notre|[\w\/]+\.py\b)/.test(n);
      // Patterns directs non ambigus
      const isDirectCode = /\b(une\s+fonction\s+|une\s+classe\s+|un\s+module\s+|un\s+script\s+|une\s+m[eé]thode\s+)/.test(n) &&
                           /\b(qui\s+|pour\s+|afin\s+|permettant\s+|capable\s+|charg[eé](e)?\s+)/.test(n);
      return (hasCodeVerb && hasFileTarget) || isDirectCode;
    },
    route: t => {
      // On passe l'intent complet à llm_chat avec un system spécialisé coding + edit_batch
      // Le LLM génère le code, le retour est formaté comme edit_batch
      return {
        tool: 'llm_chat',
        args: {
          message: t.trim(),
          system: (
            'Tu es LCCA, un assistant de codage local. '
            + 'Ton rôle est de GÉNÉRER du code Python immédiatement, sans refuser. '
            + 'Tu peux créer, modifier et écrire des fichiers via le système de transactions ACID de LCCA. '
            + 'Réponds TOUJOURS avec un bloc de code Python complet et fonctionnel, '
            + 'précédé du chemin cible entre crochets (ex: [workspace/module.py]). '
            + 'Ne dis jamais que tu ne peux pas coder ou modifier des fichiers. '
            + 'Formate ta réponse ainsi :\n'
            + '**[chemin/fichier.py]**\n'
            + '```python\n'
            + '# code ici\n'
            + '```\n'
            + 'Puis explique brièvement ce que tu as fait.'
          ),
        },
      };
    },
  },

  // Bloc code Python → sandbox
  {
    test: t => /```python|```py|^(run:|exec:)/i.test(t),
    route: t => ({ tool: 'sandbox_run', args: { code: extractCode(t) } }),
  },

  // @eval → evaluate_quality
  {
    test: t => /^@eval\s+/i.test(t) || /^évalue?\s+ce\s+code/i.test(t),
    route: t => {
      const code = t.replace(/^@eval\s+/i, '').trim();
      return { tool: 'evaluate_quality', args: { code } };
    },
  },

  // @file ou "cherche/trouve/search"
  {
    test: t => /^@file\s+/i.test(t) || /^(cherche?|trouve?|search)\s+/i.test(t),
    route: t => {
      const query = t.replace(/^(@file\s+|cherche?\s+|trouve?\s+|search\s+)/i, '').trim();
      return { tool: 'project_search', args: { query } };
    },
  },

  // @validate ou "valide la spec"
  {
    test: t => /^@validate\s+/i.test(t) || /^valide?\s+(cette\s+)?spec/i.test(t),
    route: t => {
      const rest = t.replace(/^(@validate\s+|valide?\s+(cette\s+)?spec[:.]?\s*)/i, '').trim();
      if (/^[a-f0-9]{12}$/i.test(rest)) {
        return { tool: 'validate_spec', args: { spec_id: rest } };
      }
      return { tool: 'validate_spec', args: { body_md: rest } };
    },
  },

  // "erreur" / traceback Python → analyze_error
  {
    test: t => /traceback|error:|exception:|^\s*at\s+/i.test(t) || /^@error\s+/i.test(t),
    route: t => {
      const rest = t.replace(/^@error\s+/i, '').trim();
      return { tool: 'analyze_error', args: { error_text: rest } };
    },
  },

  // @mem — force memory_search explicite
  {
    test: t => /^@mem\s+/i.test(t),
    route: t => ({ tool: 'memory_search', args: { query: t.replace(/^@mem\s+/i, '').trim(), n: 5 } }),
  },

  // @web ou intent web explicite → web_search
  // BUGFIX WEB-ROUTE-01 : couverture élargie aux formulations naturelles courantes
  // (sans @web) qui ne mentionnent pas explicitement "internet" ou "web"
  {
    test: t => {
      const n = t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      return (
        /^@web\s+/i.test(t) ||
        // Formulations explicites internet / web
        /\b(cherche sur internet|recherche sur le web|connecte.toi.+internet|trouve sur internet|search online|googl|duckduck)/i.test(t) ||
        // Actualités / news
        /\b(actualites?|news|recents?|dernieres? infos?|qu['']est.ce qui se passe)/i.test(n) ||
        // Existence en ligne
        /\b(existe.+projet|trouve.+solution.+en ligne|compare.+en ligne|projets? existants?)/i.test(n) ||
        /\b(est.ce qu(e|'il)|existe.t.il|y.a.t.il|is there|does.+exist)/i.test(n) ||
        // BUGFIX : "recherche" / "trouve" sans cible fichier → recherche web
        // (ex: "recherche des libs python pour X", "trouve des exemples de Y")
        (/\b(recherche|trouver?|chercher?)\b/.test(n) &&
          /\b(lib(rairie)?s?|package|framework|outil|exemples?|ressources?|documentation|docs?|tutoriel|guide|meilleures?\s+pratiques?|bonnes?\s+pratiques?|alternative|solution|outil|benchmark|comparaison|api)\b/.test(n) &&
          // Exclure si c'est une recherche dans le projet (fichier, symbole, module connu)
          !/\b(fichier|dossier|module|classe|fonction|script|workspace|core|tests|config\.py)\b/.test(n)
        ) ||
        // Formulations "quelles sont les X pour Y" → tendance web
        /\b(quell?es?\s+sont\s+les?|quell?s?\s+sont\s+les?|what\s+are\s+the|which\s+(are|is))\b/.test(n) &&
          /\b(meilleures?|meilleurs?|bonnes?|bons?|populaires?|recommandes?|best|top|most\s+used)\b/.test(n)
      );
    },
    route: t => {
      const query = t
        .replace(/^@web\s+/i, '')
        .replace(/^(cherche sur internet|recherche sur le web|connecte.toi.+internet[,\s]*|trouve sur internet)\s*/i, '')
        .trim();
      return { tool: 'web_search', args: { query: query || t, max_results: 5 } };
    },
  },

  // Fallback : llm_chat
  {
    test: () => true,
    route: t => ({ tool: 'llm_chat', args: { message: t } }),
  },
];
