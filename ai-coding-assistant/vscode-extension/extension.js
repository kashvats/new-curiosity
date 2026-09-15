const vscode = require('vscode');

let outputChannel;

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    outputChannel = vscode.window.createOutputChannel("AI Auditor");
    context.subscriptions.push(outputChannel);

    // --- Command: Open Dashboard (Audit) ---
    const auditDisposable = vscode.commands.registerCommand('aiProjectAuditor.start', async () => {
        const projectPath = getProjectPath();
        if (!projectPath) return;
        const projectName = getProjectName(projectPath);

        outputChannel.show(true);
        log(`[INFO] Triggering AI Audit for project: ${projectName}`);

        const statusBar = createStatusBar('$(sync~spin) AI Auditor: Running audit...');
        try {
            const result = await apiFetch('POST', '/projects/audit/run', { project_name: projectName });
            if (result.status === 'ok') {
                log(`[SUCCESS] Audit complete. Health: ${result.overall_status.toUpperCase()}`);
                await openFile(`${projectPath}/AUDIT_REPORT.md`);
            } else {
                log(`[ERROR] ${result.message}`);
            }
        } catch (err) {
            log(`[FATAL] ${err.message}. Is the backend running?`);
        } finally {
            statusBar.dispose();
        }
    });

    // --- Command: View Audit History ---
    const historyDisposable = vscode.commands.registerCommand('aiProjectAuditor.history', async () => {
        const projectPath = getProjectPath();
        if (!projectPath) return;
        const projectName = getProjectName(projectPath);

        try {
            const data = await apiFetch('GET', `/projects/audit/reports?project_name=${encodeURIComponent(projectName)}`);
            const reports = data.reports || [];
            if (reports.length === 0) {
                vscode.window.showInformationMessage(`No audit history for: ${projectName}`);
                return;
            }
            const items = reports.map(r => ({
                label: `${r.overall_status === 'critical' ? '$(error)' : r.overall_status === 'warning' ? '$(warning)' : '$(check)'} ${new Date(r.created_at).toLocaleString()}`,
                description: `Health: ${r.overall_status.toUpperCase()}`,
                detail: `Report ID: ${r.id}`,
                report: r
            }));
            const selected = await vscode.window.showQuickPick(items, {
                placeHolder: `Select a report for ${projectName}`
            });
            if (selected) {
                vscode.window.showInformationMessage(`Status: ${selected.report.overall_status.toUpperCase()} — check AUDIT_REPORT.md for full details.`);
            }
        } catch (err) {
            vscode.window.showErrorMessage(`Failed to fetch history: ${err.message}`);
        }
    });

    // --- Command: Run Security Scan (SSE-powered, no polling loop) ---
    const securityDisposable = vscode.commands.registerCommand('aiProjectAuditor.securityScan', async () => {
        const projectPath = getProjectPath();
        if (!projectPath) return;
        const projectName = getProjectName(projectPath);

        const targetUrl = await vscode.window.showInputBox({
            prompt: 'Optional: Target URL for E2E & Load Testing',
            placeHolder: 'http://localhost:8000 (leave blank to skip)'
        });
        const dbUrl = await vscode.window.showInputBox({
            prompt: 'Optional: PostgreSQL URL for DB Profiling',
            placeHolder: 'postgresql://user:pass@localhost:5432/db (leave blank to skip)'
        });

        outputChannel.show(true);
        log(`[INFO] Starting Hybrid Security Scan for: ${projectName}`);

        const statusBar = createStatusBar('$(sync~spin) AI Auditor: Scan starting...');

        try {
            // Step 1: Start the scan, get a session ID
            const startRes = await apiFetch('POST', `/projects/${encodeURIComponent(projectName)}/vulnerability_scan`, {
                target_url: targetUrl || null,
                db_url: dbUrl || null
            });
            if (startRes.status !== 'started') {
                log(`[ERROR] Could not start scan: ${startRes.message}`);
                return;
            }

            const sessionId = startRes.session_id;
            log(`[INFO] Scan session: ${sessionId}`);

            // Step 2: Open a single SSE connection. The backend PUSHES progress to us.
            // No polling loop, no wasted HTTP requests.
            const report = await new Promise((resolve, reject) => {
                const streamUrl = `http://127.0.0.1:8000/projects/vulnerability_scan/${encodeURIComponent(sessionId)}/stream`;
                
                // Use fetch with ReadableStream to consume SSE without EventSource
                // (EventSource does not support custom headers; fetch is more flexible)
                fetch(streamUrl)
                    .then(response => {
                        if (!response.ok) {
                            reject(new Error(`SSE stream failed: HTTP ${response.status}`));
                            return;
                        }
                        const reader = response.body.getReader();
                        const decoder = new TextDecoder();
                        let buffer = '';

                        const read = () => {
                            reader.read().then(({ done, value }) => {
                                if (done) { reject(new Error('Stream closed unexpectedly')); return; }

                                buffer += decoder.decode(value, { stream: true });
                                const lines = buffer.split('\n');
                                buffer = lines.pop(); // Keep incomplete last line

                                for (const line of lines) {
                                    if (line.startsWith('event: progress')) continue;
                                    if (line.startsWith('data: ')) {
                                        try {
                                            const payload = JSON.parse(line.slice(6));
                                            if (payload.progress) {
                                                log(`[STATUS] ${payload.progress}`);
                                                statusBar.text = `$(sync~spin) ${payload.progress}`;
                                            }
                                            if (payload.status === 'completed' && payload.report) {
                                                reader.cancel();
                                                resolve(payload.report);
                                                return;
                                            }
                                            if (payload.status === 'failed') {
                                                reader.cancel();
                                                reject(new Error('Scan failed on backend'));
                                                return;
                                            }
                                        } catch (_) {}
                                    }
                                }
                                read();
                            }).catch(reject);
                        };
                        read();
                    })
                    .catch(reject);
            });

            log(`[SUCCESS] Scan complete. Found ${report.vulnerabilities?.length ?? 0} vulnerabilities.`);
            statusBar.text = `$(check) AI Auditor: Scan complete`;

            // Step 3: Write the LLM-optimised SECURITY_REPORT.md
            const fs = require('fs');
            const path = require('path');
            let md = `# SECURITY FIX PROMPT\n\n`;
            md += `**System Instructions for LLM:**\n`;
            md += `You are an expert Security Engineer. Below is a list of vulnerabilities found in the codebase. `;
            md += `For each entry, open the specified file, navigate to the indicated line, and provide the exact code replacement.\n\n`;
            md += `**Overall Scan Summary:** ${report.summary}\n\n`;
            md += `<vulnerabilities>\n`;
            for (const v of (report.vulnerabilities || [])) {
                md += `  <vulnerability>\n`;
                md += `    <severity>${v.severity.toUpperCase()}</severity>\n`;
                md += `    <file>${v.file}</file>\n`;
                md += `    <line>${v.line_number}</line>\n`;
                md += `    <issue_type>${v.issue_type}</issue_type>\n`;
                md += `    <explanation>${v.explanation}</explanation>\n`;
                md += `  </vulnerability>\n`;
            }
            md += `</vulnerabilities>\n`;

            const mdPath = path.join(projectPath, 'SECURITY_REPORT.md');
            fs.writeFileSync(mdPath, md);
            await openFile(mdPath, vscode.ViewColumn.Beside);

            // Step 4: Inject inline diagnostics (squiggly lines)
            const diagnosticCollection = vscode.languages.createDiagnosticCollection('aiSecurity');
            diagnosticCollection.clear();
            const diagnosticsMap = new Map();
            for (const v of (report.vulnerabilities || [])) {
                const filePath = path.join(projectPath, v.file);
                const uri = vscode.Uri.file(filePath);
                const severity = ['critical', 'high'].includes(v.severity?.toLowerCase())
                    ? vscode.DiagnosticSeverity.Error
                    : vscode.DiagnosticSeverity.Warning;
                const line = Math.max(0, (v.line_number || 1) - 1);
                const diagnostic = new vscode.Diagnostic(
                    new vscode.Range(line, 0, line, 100),
                    `[AI Security] ${v.issue_type}: ${v.explanation}`,
                    severity
                );
                if (!diagnosticsMap.has(uri.fsPath)) diagnosticsMap.set(uri.fsPath, []);
                diagnosticsMap.get(uri.fsPath).push(diagnostic);
            }
            for (const [fsPath, diags] of diagnosticsMap.entries()) {
                diagnosticCollection.set(vscode.Uri.file(fsPath), diags);
            }
            log(`[INFO] Injected ${report.vulnerabilities?.length ?? 0} inline diagnostics.`);

        } catch (err) {
            log(`[FATAL] ${err.message}`);
        } finally {
            setTimeout(() => statusBar.dispose(), 5000);
        }
    });

    context.subscriptions.push(auditDisposable, historyDisposable, securityDisposable);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getProjectPath() {
    if (!vscode.workspace.workspaceFolders?.length) {
        vscode.window.showErrorMessage('AI Auditor: No workspace folder is open.');
        return null;
    }
    return vscode.workspace.workspaceFolders[0].uri.fsPath;
}

function getProjectName(projectPath) {
    return projectPath.split(/[/\\]/).pop();
}

function log(message) {
    outputChannel.appendLine(`[${new Date().toLocaleTimeString()}] ${message}`);
}

function createStatusBar(text) {
    const bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    bar.text = text;
    bar.show();
    return bar;
}

async function openFile(filePath, column = vscode.ViewColumn.Active) {
    try {
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        await vscode.window.showTextDocument(doc, column);
    } catch {
        log(`[WARN] Could not open file: ${filePath}`);
    }
}

/**
 * Unified fetch wrapper replacing raw http.request() callbacks.
 * Uses the native fetch API available in VS Code 1.80+.
 */
async function apiFetch(method, path, body = null) {
    const url = `http://127.0.0.1:8000${path}`;
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(url, options);
    if (!response.ok) {
        throw new Error(`Backend error: HTTP ${response.status} on ${path}`);
    }
    return response.json();
}

function deactivate() {}

module.exports = { activate, deactivate };
