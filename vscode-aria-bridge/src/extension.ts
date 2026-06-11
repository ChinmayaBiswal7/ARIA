/**
 * ARIA VS Code Bridge Extension — src/extension.ts
 * =================================================
 *
 * Sends real VS Code workspace state to ARIA's local HTTP bridge server.
 *
 * Data pushed on each sync:
 *   active_file    — absolute path of the currently open file
 *   language_id    — VS Code language identifier (python, typescript, etc.)
 *   cursor_line    — current cursor line (1-indexed)
 *   selection      — selected text in the active editor (empty if nothing selected)
 *   diagnostics    — errors/warnings from the Problems panel for the active file
 *   git_branch     — current git branch (via VS Code's built-in git extension API)
 *   open_files     — list of all open file paths in the current workspace
 *   terminal_cwd   — working directory of the active terminal (if any)
 */

import * as vscode from "vscode";
import * as http from "http";
import * as path from "path";

// ── Constants ──────────────────────────────────────────────────────────────────

const EXTENSION_ID = "aria-vscode-bridge";

// ── State ──────────────────────────────────────────────────────────────────────

let syncTimer: NodeJS.Timeout | undefined;
let statusBarItem: vscode.StatusBarItem;
let lastSyncOk = false;

// ── Activation ────────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
  console.log("[ARIA Bridge] Extension activated.");

  // Status bar — shows sync health at a glance
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.command = "aria.syncState";
  statusBarItem.text = "$(plug) ARIA";
  statusBarItem.tooltip = "ARIA VS Code Bridge — click to sync now";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand("aria.syncState", () => syncNow()),
    vscode.commands.registerCommand("aria.startBridge", () => startAutoSync(context)),
    vscode.commands.registerCommand("aria.stopBridge", () => stopAutoSync())
  );

  // Auto-start if enabled
  const cfg = vscode.workspace.getConfiguration("aria");
  if (cfg.get<boolean>("enabled", true)) {
    startAutoSync(context);
  }

  // Re-sync on editor focus change
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => syncNow()),
    vscode.window.onDidChangeTextEditorSelection(() => syncNow())
  );
}

export function deactivate(): void {
  stopAutoSync();
}

// ── Sync Logic ────────────────────────────────────────────────────────────────

function startAutoSync(context: vscode.ExtensionContext): void {
  stopAutoSync();
  const cfg = vscode.workspace.getConfiguration("aria");
  const intervalSec = cfg.get<number>("syncIntervalSeconds", 5);
  if (intervalSec <= 0) {
    console.log("[ARIA Bridge] Auto-sync disabled (interval = 0).");
    return;
  }
  syncNow(); // Immediate first sync
  syncTimer = setInterval(() => syncNow(), intervalSec * 1000);
  console.log(`[ARIA Bridge] Auto-sync started (every ${intervalSec}s).`);
}

function stopAutoSync(): void {
  if (syncTimer) {
    clearInterval(syncTimer);
    syncTimer = undefined;
    console.log("[ARIA Bridge] Auto-sync stopped.");
  }
}

async function syncNow(): Promise<void> {
  const payload = await buildPayload();
  const cfg = vscode.workspace.getConfiguration("aria");
  const baseUrl = cfg.get<string>("bridgeUrl", "http://127.0.0.1:9821");

  postJson(`${baseUrl}/vscode/state`, payload)
    .then(() => {
      lastSyncOk = true;
      statusBarItem.text = "$(check) ARIA";
      statusBarItem.tooltip = `ARIA synced: ${path.basename(payload.active_file || "no file")}`;
    })
    .catch((err) => {
      lastSyncOk = false;
      statusBarItem.text = "$(debug-disconnect) ARIA";
      statusBarItem.tooltip = `ARIA bridge offline — ${err.message}`;
    });
}

// ── Payload Builder ───────────────────────────────────────────────────────────

interface DiagnosticEntry {
  severity: string;
  message:  string;
  line:     number;
  source:   string;
}

interface WorkspacePayload {
  active_file:   string;
  language_id:   string;
  cursor_line:   number;
  selection:     string;
  diagnostics:   DiagnosticEntry[];
  git_branch:    string;
  open_files:    string[];
  terminal_cwd:  string;
}

async function buildPayload(): Promise<WorkspacePayload> {
  const editor = vscode.window.activeTextEditor;

  // ── Active file & language ────────────────────────────────────────────────
  const activeFile   = editor?.document.uri.fsPath ?? "";
  const languageId   = editor?.document.languageId ?? "";
  const cursorLine   = editor ? editor.selection.active.line + 1 : 0; // 1-indexed

  // ── Selection ─────────────────────────────────────────────────────────────
  let selection = "";
  if (editor && !editor.selection.isEmpty) {
    selection = editor.document.getText(editor.selection);
    // Truncate very long selections to avoid flooding ARIA
    if (selection.length > 2000) {
      selection = selection.slice(0, 2000) + "\n... (truncated)";
    }
  }

  // ── Diagnostics for active file only ─────────────────────────────────────
  const diagnostics: DiagnosticEntry[] = [];
  if (editor) {
    const uriDiags = vscode.languages.getDiagnostics(editor.document.uri);
    for (const d of uriDiags) {
      diagnostics.push({
        severity: vscode.DiagnosticSeverity[d.severity], // "Error" | "Warning" | "Information" | "Hint"
        message:  d.message,
        line:     d.range.start.line + 1,
        source:   d.source ?? "",
      });
    }
  }

  // ── Git branch ────────────────────────────────────────────────────────────
  let gitBranch = "";
  try {
    // Access VS Code's built-in git extension
    const gitExt = vscode.extensions.getExtension("vscode.git");
    if (gitExt?.isActive) {
      const git = gitExt.exports.getAPI(1);
      if (git.repositories.length > 0) {
        gitBranch = git.repositories[0].state.HEAD?.name ?? "";
      }
    }
  } catch {
    // Git extension not available — leave branch empty
  }

  // ── Open files across all tab groups ─────────────────────────────────────
  const openFiles: string[] = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      const input = tab.input as { uri?: vscode.Uri };
      if (input?.uri?.fsPath) {
        openFiles.push(input.uri.fsPath);
      }
    }
  }

  // ── Active terminal CWD ───────────────────────────────────────────────────
  let terminalCwd = "";
  try {
    const term = vscode.window.activeTerminal;
    if (term) {
      const cwd = await term.shellIntegration?.cwd;
      terminalCwd = cwd?.fsPath ?? "";
    }
  } catch {
    // shellIntegration may not be available in all VS Code versions
  }

  return {
    active_file:  activeFile,
    language_id:  languageId,
    cursor_line:  cursorLine,
    selection:    selection,
    diagnostics:  diagnostics,
    git_branch:   gitBranch,
    open_files:   openFiles,
    terminal_cwd: terminalCwd,
  };
}

// ── HTTP Helper ───────────────────────────────────────────────────────────────

function postJson(url: string, data: object): Promise<void> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const parsed = new URL(url);

    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port:     parseInt(parsed.port || "80", 10),
      path:     parsed.pathname,
      method:   "POST",
      headers:  {
        "Content-Type":   "application/json",
        "Content-Length": Buffer.byteLength(body),
      },
    };

    const req = http.request(options, (res) => {
      res.resume(); // Drain response
      if (res.statusCode && res.statusCode < 400) {
        resolve();
      } else {
        reject(new Error(`HTTP ${res.statusCode}`));
      }
    });

    req.setTimeout(2000, () => {
      req.destroy(new Error("Request timeout — ARIA bridge not responding"));
    });

    req.on("error", reject);
    req.write(body);
    req.end();
  });
}
