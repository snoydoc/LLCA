import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { join } from 'path';
import { existsSync } from 'fs';  // FIX: existsSync appartient à 'fs', pas à 'path'
import { timeoutForTool, DEFAULT_TIMEOUT_MS } from './mcp-timeouts';
import { McpReconnect } from './mcp-reconnect';

// ─── Types ────────────────────────────────────────────────────────────────────
interface PendingRequest {
  resolve: (v: unknown) => void;
  reject:  (e: Error)   => void;
  timer:   NodeJS.Timeout;
}

export interface BridgeStatus {
  status: 'connecting' | 'connected' | 'disconnected' | 'error';
}

// UI-07 : callback pour les tokens de streaming
export type TokenCallback = (reqId: number, token: string) => void;

// ─── McpBridge ────────────────────────────────────────────────────────────────
export class McpBridge {
  private proc:       ChildProcess | null    = null;
  private rl:         readline.Interface | null = null;
  private pending     = new Map<number, PendingRequest>();
  private requestId   = 0;
  private _status:    BridgeStatus['status'] = 'disconnected';
  private stopped     = false;
  // UI-07 : callback enregistré par main.ts pour forwarder les tokens au renderer
  private _onToken:   TokenCallback | null   = null;

  private readonly RETRY_DELAYS = [1000, 2000, 5000] as const;
  private readonly reconnect: McpReconnect;
  private readonly workspacePath: string;

  constructor(workspacePath: string) {
    this.workspacePath = workspacePath;
    this.reconnect = new McpReconnect({
      retryDelays: this.RETRY_DELAYS,
      onRestart:   () => this.start(),
      onGiveUp:    () => { this._status = 'error'; },
    });
  }

  // UI-07 : enregistre le callback de streaming tokens
  onToken(cb: TokenCallback): void {
    this._onToken = cb;
  }

  // ── Démarrage ──────────────────────────────────────────────────────────────
  async start(): Promise<void> {
    this.stopped = false;
    this.reconnect.reset();
    this._status = 'connecting';

    const pythonExe = this.resolvePython();
    const mcpScript = join(this.workspacePath, 'core', 'mcp_server.py');

    if (!existsSync(mcpScript)) {
      this._status = 'error';
      throw new Error(`McpServer introuvable : ${mcpScript}`);
    }

    this.proc = spawn(pythonExe, [mcpScript], {
      stdio:       ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      cwd:         this.workspacePath,
      env: {
        ...process.env,
        // UI-06: force Ollama en mode CPU + ancien engine (Quadro M2000M incompatible new engine)
        OLLAMA_NEW_ENGINE:    '0',
        OLLAMA_NUM_GPU:       '0',
        CUDA_VISIBLE_DEVICES: 'NoDevFiles',
        OLLAMA_MODELS:        'D:\\Continue\\Ollama\\models',
      },
    });

    this.rl = readline.createInterface({ input: this.proc.stdout! });
    this.rl.on('line', (line) => this.onLine(line));

    this.proc.stderr?.on('data', (d: Buffer) => {
      // Logs Python INFO/WARNING/ERROR -- decodeage UTF-8 explicite via console.error
      const text = d.toString('utf8');
      console.error('[mcp-server]', text.trimEnd());
    });

    this.proc.on('close', (code) => this.onCrash(code));

    // FIX: attendre le signal {"lcca":"ready"} avant d'initier le handshake.
    await this.waitForReady();
    await this.initialize();
    this._status = 'connected';
    this.retryCount = 0;
  }

  // ── Attente du signal {"lcca":"ready"} ────────────────────────────────────
  private waitForReady(): Promise<void> {
    return new Promise((resolve, reject) => {
      const READY_TIMEOUT = 15_000;
      let done = false;

      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        this.rl?.off('line', onLine);
        reject(new Error('MCP ready timeout (15s) — le serveur Python ne s\'est pas signalé'));
      }, READY_TIMEOUT);

      const onLine = (line: string) => {
        if (done) return;
        try {
          const msg = JSON.parse(line);
          if (msg?.lcca === 'ready') {
            done = true;
            clearTimeout(timer);
            this.rl?.off('line', onLine);
            console.log(`[McpBridge] ready reçu — protocol=${msg.protocol ?? 'unknown'}`);
            resolve();
          }
        } catch { /* ligne non-JSON pendant le boot, ignorer */ }
      };

      this.rl?.on('line', onLine);
    });
  }

  // ── Handshake JSON-RPC initialize ──────────────────────────────────────────
  private async initialize(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const id = ++this.requestId;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('MCP initialize timeout'));
      }, DEFAULT_TIMEOUT_MS);
      this.pending.set(id, {
        resolve: () => resolve(),
        reject,
        timer,
      });
      this.send({
        jsonrpc: '2.0',
        id,
        method: 'initialize',
        params: {
          protocolVersion: '2024-11-05',
          clientInfo: { name: 'adham-desktop', version: '1.0.0' },
          capabilities: {},
        },
      });
    });
    // notification sans réponse attendue
    this.send({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
  }

  // ── Appel tool MCP ─────────────────────────────────────────────────────────
  async call(method: string, params: object): Promise<unknown> {
    if (
      this._status === 'disconnected' ||
      this._status === 'error' ||
      this._status === 'connecting'
    ) {
      throw new Error(
        `McpBridge non disponible (état: ${this._status}). ` +
        `Le serveur MCP Python n'est pas encore démarré — vérifiez que le venv est activé ` +
        `et que D:\\LLMCodeAgent\\core\\mcp_server.py est accessible.`
      );
    }
    const id       = ++this.requestId;
    const toolName = (params as any)?.name as string ?? '';
    const timeoutMs = timeoutForTool(toolName);

    console.log(`[McpBridge] call ${toolName} — timeout=${timeoutMs}ms`);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP timeout [${method}/${toolName}] après ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ jsonrpc: '2.0', id, method, params });
    });
  }

  // ── Écriture stdin ─────────────────────────────────────────────────────────
  private send(obj: object): void {
    if (!this.proc?.stdin?.writable) {
      throw new Error('McpBridge: stdin non disponible — le processus MCP Python n\'est pas actif.');
    }
    this.proc.stdin.write(JSON.stringify(obj) + '\n');
  }

  // ── Lecture stdout ─────────────────────────────────────────────────────────
  private onLine(line: string): void {
    if (!line.trim()) return;
    try {
      const msg = JSON.parse(line) as {
        id?:      number;
        lcca?:    string;
        protocol?: string;
        method?:  string;
        params?:  { req_id?: number; token?: string };
        result?:  unknown;
        error?:   { code: number; message: string };
      };

      // Message de démarrage {"lcca":"ready"} — pas d'id
      if (msg.lcca === 'ready') {
        console.log(`[McpBridge] serveur prêt — protocol=${msg.protocol ?? 'unknown'}`);
        return;
      }

      // UI-07 : notification push lcca/token (sans id — push server→client)
      if (msg.method === 'lcca/token' && msg.params) {
        const { req_id, token } = msg.params;
        if (this._onToken && req_id !== undefined && token !== undefined) {
          this._onToken(req_id, token);
        }
        return;
      }

      // Réponse JSON-RPC classique (avec id)
      if (msg.id !== undefined) {
        const pending = this.pending.get(msg.id);
        if (pending) {
          clearTimeout(pending.timer);
          this.pending.delete(msg.id);
          if (msg.error) {
            pending.reject(new Error(`[${msg.error.code}] ${msg.error.message}`));
          } else {
            pending.resolve(msg.result);
          }
        }
      }
    } catch {
      // Ligne non-JSON (logs Python qui arrivent sur stdout) → ignorer
    }
  }

  // ── Crash / reconnexion ────────────────────────────────────────────────────
  private onCrash(code: number | null): void {
    this._status = 'error';
    this.reconnect.onCrash(code, (err) => {
      for (const [, pending] of this.pending) {
        clearTimeout(pending.timer);
        pending.reject(err);
      }
      this.pending.clear();
    });
  }

  // ── Résolution de l'exécutable Python ─────────────────────────────────────
  private resolvePython(): string {
    if (process.env.LCCA_PYTHON) return process.env.LCCA_PYTHON;
    const candidates = [
      join(this.workspacePath, 'venv', 'Scripts', 'python.exe'),
      join(this.workspacePath, 'venv', 'bin', 'python'),
      'python',
    ];
    for (const c of candidates) {
      if (existsSync(c)) return c;
    }
    return 'python';
  }

  // ── Arrêt propre ──────────────────────────────────────────────────────────
  async stop(): Promise<void> {
    this.stopped = true;
    this.reconnect.stop();
    this._status = 'disconnected';
    this.rl?.close();
    this.proc?.stdin?.end();
    await new Promise<void>((res) => {
      const t = setTimeout(() => { this.proc?.kill('SIGKILL'); res(); }, 3000);
      this.proc?.on('close', () => { clearTimeout(t); res(); });
    });
    this.proc = null;
    this.rl   = null;
  }

  async restart(): Promise<void> {
    await this.stop();
    this.retryCount = 0;
    await this.start();
  }

  getStatus(): BridgeStatus {
    return { status: this._status };
  }
}
