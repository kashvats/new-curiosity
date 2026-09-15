const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

let outputChannel;
let lastVerifiedSessionId = null;
let lastImprovementCycleId = null;
const proposedDocuments = new Map();

class ProposedContentProvider {
    provideTextDocumentContent(uri) {
        return proposedDocuments.get(uri.toString()) || '// Proposed content is no longer available.\n';
    }
}

/** @param {vscode.ExtensionContext} context */
function activate(context) {
    outputChannel = vscode.window.createOutputChannel('AI Coding Assistant');
    context.subscriptions.push(outputChannel);
    context.subscriptions.push(
        vscode.workspace.registerTextDocumentContentProvider('ai-proposed', new ProposedContentProvider())
    );

    // Core IDE modes.
    register(context, 'aiCodingAssistant.ask', () => runIdeMode('ask'));
    register(context, 'aiCodingAssistant.plan', () => runIdeMode('plan'));
    register(context, 'aiCodingAssistant.edit', () => runIdeMode('edit'));
    register(context, 'aiCodingAssistant.fix', () => runIdeMode('fix'));
    register(context, 'aiCodingAssistant.review', () => runIdeMode('review'));
    register(context, 'aiCodingAssistant.agent', () => runIdeMode('agent'));
    register(context, 'aiCodingAssistant.applyLast', applyLastVerifiedRepair);
    register(context, 'aiCodingAssistant.showActivity', () => outputChannel.show(true));
    register(context, 'aiCodingAssistant.showLastDiff', showLastVerifiedDiff);
    register(context, 'aiCodingAssistant.browseRepository', browseRepository);
    register(context, 'aiCodingAssistant.searchCode', searchCode);
    register(context, 'aiCodingAssistant.searchSymbols', searchSymbols);
    register(context, 'aiCodingAssistant.improvementCenter', showImprovementCenter);
    register(context, 'aiCodingAssistant.improveProject', runImprovementCycle);
    register(context, 'aiCodingAssistant.cancelImprovement', cancelImprovementCycle);
    register(context, 'aiCodingAssistant.autonomyReadiness', showAutonomyReadiness);
    register(context, 'aiCodingAssistant.schedulerStatus', showSchedulerStatus);
    register(context, 'aiCodingAssistant.runSchedulerTick', runSchedulerTickCommand);
    register(context, 'aiCodingAssistant.schedulerEmergencyStop', schedulerEmergencyStop);
    register(context, 'aiCodingAssistant.schedulerSimulate', simulateSchedulerCommand);
    register(context, 'aiCodingAssistant.schedulerMetrics', showSchedulerMetrics);
    register(context, 'aiCodingAssistant.schedulerIntegrations', showSchedulerIntegrations);
    register(context, 'aiCodingAssistant.schedulerDrDrill', runSchedulerDrDrill);
    register(context, 'aiCodingAssistant.schedulerDeploymentHealth', showSchedulerDeploymentHealth);
    register(context, 'aiCodingAssistant.stagingReleaseCenter', showStagingReleaseCenter);
    register(context, 'aiCodingAssistant.stagingProviderCenter', showStagingProviderCenter);
    register(context, 'aiCodingAssistant.productionGovernance', showProductionGovernanceCenter);
    register(context, 'aiCodingAssistant.productionLearning', showProductionLearning);
    register(context, 'aiCodingAssistant.productionCertification', showProductionCertification);
    register(context, 'aiCodingAssistant.intelligenceEfficiency', showIntelligenceEfficiency);

    // Existing project-auditor commands remain available and use the same backend.
    register(context, 'aiProjectAuditor.start', runAudit);
    register(context, 'aiProjectAuditor.history', showAuditHistory);
    register(context, 'aiProjectAuditor.securityScan', runSecurityScan);

    log('[READY] AI Coding Assistant extension activated. Modes: Ask / Plan / Edit / Fix / Review / Agent.');
}

function register(context, command, fn) {
    context.subscriptions.push(vscode.commands.registerCommand(command, fn));
}

function backendUrl() {
    return vscode.workspace.getConfiguration('aiCodingAssistant').get('backendUrl', 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function getWorkspace() {
    if (!vscode.workspace.workspaceFolders?.length) {
        vscode.window.showErrorMessage('AI Coding Assistant: Open a workspace folder first.');
        return null;
    }
    const folder = vscode.workspace.workspaceFolders[0];
    return { root: folder.uri.fsPath, name: path.basename(folder.uri.fsPath) };
}

function editorContext(workspace) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return { current_file: null, files: [], selected_text: '', diagnostics: [] };
    let currentFile = null;
    try {
        const rel = path.relative(workspace.root, editor.document.uri.fsPath).replace(/\\/g, '/');
        if (rel && !rel.startsWith('..')) currentFile = rel;
    } catch (_) {}
    const selectedText = editor.selection.isEmpty ? '' : editor.document.getText(editor.selection);
    const diagnostics = vscode.languages.getDiagnostics(editor.document.uri).slice(0, 100).map(d => ({
        message: d.message,
        severity: ['error', 'warning', 'information', 'hint'][d.severity] || String(d.severity),
        source: d.source || '',
        code: typeof d.code === 'object' ? d.code.value : d.code,
        line: d.range.start.line + 1,
        character: d.range.start.character + 1
    }));
    return {
        current_file: currentFile,
        files: currentFile ? [currentFile] : [],
        selected_text: selectedText,
        diagnostics
    };
}

async function runIdeMode(mode) {
    const workspace = getWorkspace();
    if (!workspace) return;
    const ctx = editorContext(workspace);
    const defaults = {
        ask: 'Explain the selected/current code and answer my question.',
        plan: 'Create a safe implementation plan for this change.',
        edit: 'Make the requested code change with the smallest safe patch.',
        fix: 'Diagnose and fix the selected/current issue, retrying from validation evidence if needed.',
        review: 'Review the selected/current code for correctness, regressions, maintainability, and security.',
        agent: 'Implement this task end-to-end: inspect, plan, edit, validate, review, and prepare a verified patch.'
    };
    const task = await vscode.window.showInputBox({
        prompt: `AI ${mode.toUpperCase()} — describe the task`,
        value: defaults[mode],
        ignoreFocusOut: true
    });
    if (!task) return;

    outputChannel.show(true);
    log(`[${mode.toUpperCase()}] ${task}`);
    const statusBar = createStatusBar(`$(sync~spin) AI ${capitalize(mode)}: collecting context...`);

    try {
        const start = await apiFetch('POST', '/ide/sessions', {
            mode,
            task,
            project_name: workspace.name,
            files: ctx.files,
            current_file: ctx.current_file,
            selected_text: ctx.selected_text,
            diagnostics: ctx.diagnostics,
            terminal_output: ''
        });
        const sessionId = start.session_id;
        log(`[SESSION] ${sessionId}`);
        await consumeIdeEventStream(sessionId, statusBar);
        const session = await apiFetch('GET', `/ide/sessions/${encodeURIComponent(sessionId)}`);
        await presentIdeResult(session, workspace);
    } catch (err) {
        log(`[ERROR] ${err.message}`);
        vscode.window.showErrorMessage(`AI ${capitalize(mode)} failed: ${err.message}`);
    } finally {
        statusBar.dispose();
    }
}

async function consumeIdeEventStream(sessionId, statusBar) {
    const response = await fetch(`${backendUrl()}/ide/sessions/${encodeURIComponent(sessionId)}/events/stream`);
    if (!response.ok) throw new Error(`Activity stream failed: HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            if (!block.trim() || block.startsWith(':')) continue;
            let eventType = 'message';
            let data = null;
            for (const line of block.split('\n')) {
                if (line.startsWith('event:')) eventType = line.slice(6).trim();
                if (line.startsWith('data:')) {
                    try { data = JSON.parse(line.slice(5).trim()); } catch (_) {}
                }
            }
            if (eventType === 'end') return;
            if (data) {
                const message = data.message || eventType.replace(/_/g, ' ');
                statusBar.text = `$(sync~spin) AI Agent: ${message}`;
                log(`[${eventType.toUpperCase()}] ${message}`);
                if (eventType === 'validation_finished' && data.payload?.checks) {
                    for (const check of data.payload.checks) {
                        const icon = check.passed ? '✓' : '✗';
                        log(`  ${icon} ${(check.args || []).join(' ')} (${check.duration_ms ?? '?'} ms)`);
                        if (!check.passed && check.stderr) log(`    ${String(check.stderr).slice(-1200)}`);
                    }
                }
            }
        }
    }
}

async function presentIdeResult(session, workspace) {
    if (session.status === 'failed') {
        throw new Error(session.error || 'IDE session failed');
    }
    const result = session.result || {};
    const mode = result.mode || session.mode;

    if (mode === 'ask') {
        await openMarkdown(`AI Ask — ${workspace.name}`, result.answer || 'No answer returned.');
        return;
    }
    if (mode === 'plan') {
        await openMarkdown(`AI Plan — ${workspace.name}`, renderPlan(result.plan));
        return;
    }
    if (mode === 'review') {
        await openMarkdown(`AI Review — ${workspace.name}`, renderReview(result));
        return;
    }

    const repair = result.repair || {};
    if (repair.status !== 'verified') {
        await openMarkdown(`AI ${capitalize(mode)} — Needs attention`, renderRepairSummary(repair));
        vscode.window.showWarningMessage(`AI ${capitalize(mode)} could not produce a verified patch. See the activity log.`);
        return;
    }

    lastVerifiedSessionId = session.id;
    log(`[VERIFIED] ${repair.proposed_changes?.length || 0} file(s), quality ${repair.quality?.score ?? 'n/a'}. Awaiting approval.`);
    await showRepairDiffs(session, workspace);
    const choice = await vscode.window.showInformationMessage(
        `Verified patch ready (${repair.proposed_changes?.length || 0} file(s), quality ${repair.quality?.score ?? 'n/a'}).`,
        'Apply Verified Repair', 'Keep for Later'
    );
    if (choice === 'Apply Verified Repair') await applySessionRepair(session.id);
}

async function showRepairDiffs(session, workspace) {
    const changes = session.result?.repair?.proposed_changes || [];
    if (!changes.length) return;
    let selected = changes[0];
    if (changes.length > 1) {
        const picked = await vscode.window.showQuickPick(changes.map(change => ({
            label: change.path,
            description: change.action,
            detail: change.reason || '',
            change
        })), { placeHolder: 'Choose a proposed file to preview. Other files remain available in the session.' });
        if (picked) selected = picked.change;
    }
    let originalUri;
    if (selected.action === 'create') {
        originalUri = vscode.Uri.from({
            scheme: 'ai-proposed', path: `/${selected.path}`,
            query: `base=${encodeURIComponent(session.id)}`
        });
        proposedDocuments.set(originalUri.toString(), '');
    } else {
        originalUri = vscode.Uri.file(path.join(workspace.root, selected.path));
    }
    const proposedUri = vscode.Uri.from({
        scheme: 'ai-proposed',
        path: `/${selected.path}`,
        query: `session=${encodeURIComponent(session.id)}`
    });
    proposedDocuments.set(proposedUri.toString(), selected.content || '');
    await vscode.commands.executeCommand(
        'vscode.diff', originalUri, proposedUri,
        `AI Verified Diff — ${selected.path}`,
        { preview: true }
    );
}

async function showLastVerifiedDiff() {
    if (!lastVerifiedSessionId) {
        vscode.window.showInformationMessage('No verified IDE session is available in this VS Code window yet.');
        return;
    }
    const workspace = getWorkspace();
    if (!workspace) return;
    const session = await apiFetch('GET', `/ide/sessions/${encodeURIComponent(lastVerifiedSessionId)}`);
    await showRepairDiffs(session, workspace);
}

async function browseRepository() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const data = await apiFetch('GET', `/ide/tree?project_name=${encodeURIComponent(workspace.name)}`);
        const picked = await vscode.window.showQuickPick((data.files || []).map(item => ({
            label: item.path, description: `${item.size} bytes`, item
        })), { placeHolder: `Files in ${workspace.name}`, matchOnDescription: true });
        if (picked) await openFile(path.join(workspace.root, picked.item.path));
    } catch (err) { vscode.window.showErrorMessage(`Repository browse failed: ${err.message}`); }
}

async function searchCode() {
    const workspace = getWorkspace();
    if (!workspace) return;
    const q = await vscode.window.showInputBox({ prompt: 'Search project text/code' });
    if (!q) return;
    try {
        const data = await apiFetch('GET', `/ide/code-search?project_name=${encodeURIComponent(workspace.name)}&q=${encodeURIComponent(q)}`);
        const picked = await vscode.window.showQuickPick((data.results || []).map(item => ({
            label: `${item.path}:${item.line}`, description: item.preview, item
        })), { placeHolder: `Matches for “${q}”`, matchOnDescription: true });
        if (picked) await openFileAtLine(path.join(workspace.root, picked.item.path), picked.item.line);
    } catch (err) { vscode.window.showErrorMessage(`Code search failed: ${err.message}`); }
}

async function searchSymbols() {
    const workspace = getWorkspace();
    if (!workspace) return;
    const q = await vscode.window.showInputBox({ prompt: 'Search functions/classes (blank shows all)', value: '' });
    if (q === undefined) return;
    try {
        const data = await apiFetch('GET', `/ide/symbols?project_name=${encodeURIComponent(workspace.name)}&q=${encodeURIComponent(q)}`);
        const picked = await vscode.window.showQuickPick((data.matches || []).map(item => ({
            label: `$(${item.kind === 'class' ? 'symbol-class' : 'symbol-method'}) ${item.name}`,
            description: item.path, item
        })), { placeHolder: `Symbols${q ? ` matching “${q}”` : ''}`, matchOnDescription: true });
        if (picked) {
            const hits = await apiFetch('GET', `/ide/code-search?project_name=${encodeURIComponent(workspace.name)}&q=${encodeURIComponent(picked.item.name)}`);
            const exact = (hits.results || []).find(row => row.path === picked.item.path);
            await openFileAtLine(path.join(workspace.root, picked.item.path), exact?.line || 1);
        }
    } catch (err) { vscode.window.showErrorMessage(`Symbol search failed: ${err.message}`); }
}

async function applyLastVerifiedRepair() {
    if (!lastVerifiedSessionId) {
        const entered = await vscode.window.showInputBox({ prompt: 'Verified IDE session ID to apply' });
        if (!entered) return;
        return applySessionRepair(entered.trim());
    }
    return applySessionRepair(lastVerifiedSessionId);
}

async function applySessionRepair(sessionId) {
    const confirm = await vscode.window.showWarningMessage(
        'Apply the exact verified patch? A snapshot is created first and machine checks run again after application. Failed post-checks are rolled back automatically.',
        { modal: true }, 'Apply'
    );
    if (confirm !== 'Apply') return;
    const bar = createStatusBar('$(sync~spin) AI Agent: applying verified repair...');
    try {
        const result = await apiFetch('POST', `/ide/sessions/${encodeURIComponent(sessionId)}/apply`, { confirm: true });
        if (result.status === 'applied') {
            log(`[APPLIED] Snapshot ${result.snapshot_id || 'n/a'}; post-apply verification passed.`);
            vscode.window.showInformationMessage('Verified repair applied and post-apply checks passed.');
        } else if (result.status === 'rolled_back') {
            log(`[ROLLED BACK] ${result.rollback_reason || 'Post-apply verification failed.'}`);
            vscode.window.showErrorMessage('Patch failed post-apply verification and was automatically rolled back.');
        } else {
            vscode.window.showWarningMessage(`Apply finished with status: ${result.status}`);
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Could not apply verified repair: ${err.message}`);
    } finally {
        bar.dispose();
    }
}

function renderPlan(plan) {
    if (!plan) return '# Plan\n\nNo plan returned.';
    let md = `# ${plan.goal || 'Implementation Plan'}\n\n${plan.summary || ''}\n\n`;
    for (const phase of (plan.phases || [])) {
        md += `## Phase ${phase.id ?? ''}: ${phase.title || ''}\n\n${phase.description || ''}\n\n`;
        if (phase.success_criteria?.length) md += `**Success criteria:**\n${phase.success_criteria.map(v => `- ${v}`).join('\n')}\n\n`;
    }
    return md;
}

function renderReview(result) {
    const review = result.review || {};
    const security = result.security || {};
    return `# AI Review\n\n**Approved:** ${review.approved ? 'Yes' : 'No'}  \n**Risk:** ${review.risk || 'unknown'}\n\n## Summary\n${review.summary || ''}\n\n## Findings\n${(review.findings || []).map(v => `- ${v}`).join('\n') || '- None returned'}\n\n## Security\n**Approved:** ${security.approved ? 'Yes' : 'No'}\n\n${(security.findings || []).map(v => `- ${v.message || v}`).join('\n') || '- No findings'}\n`;
}

function renderRepairSummary(repair) {
    return `# Repair Result\n\n**Status:** ${repair.status || 'unknown'}\n\n**Reason:** ${repair.reason || repair.note || ''}\n\n**Attempts:** ${(repair.attempts || []).length}\n\n\`\`\`json\n${JSON.stringify(repair, null, 2).slice(0, 50000)}\n\`\`\`\n`;
}

async function openMarkdown(title, content) {
    const doc = await vscode.workspace.openTextDocument({ language: 'markdown', content: `# ${title}\n\n${content}` });
    await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside, true);
}

// ---- Part 6 improvement governance ----------------------------------------
async function showImprovementCenter() {
    const workspace = getWorkspace();
    if (!workspace) return;
    const bar = createStatusBar('$(sync~spin) AI Improvement: loading project state...');
    try {
        const [health, cycles, policy, readiness, scheduler] = await Promise.all([
            apiFetch('GET', `/improvements/health?project_name=${encodeURIComponent(workspace.name)}&run_checks=false`),
            apiFetch('GET', `/improvements/cycles?project_name=${encodeURIComponent(workspace.name)}&limit=10`),
            apiFetch('GET', `/improvements/policies/${encodeURIComponent(workspace.name)}`),
            apiFetch('GET', `/improvements/readiness?project_name=${encodeURIComponent(workspace.name)}`),
            apiFetch('GET', `/improvements/scheduler/status?project_name=${encodeURIComponent(workspace.name)}`)
        ]);
        await openMarkdown(`Improvement Center — ${workspace.name}`, renderImprovementCenter(health, cycles.cycles || [], policy, readiness, scheduler));
    } catch (err) {
        vscode.window.showErrorMessage(`Improvement Center failed: ${err.message}`);
    } finally { bar.dispose(); }
}

async function runImprovementCycle() {
    const workspace = getWorkspace();
    if (!workspace) return;
    const mode = await vscode.window.showQuickPick([
        { label: '$(tools) Manual improvement', description: 'Rank candidates, choose one, verify it, then require approval', policy: 'manual' },
        { label: '$(eye) Observe only', description: 'Measure and rank without generating a repair', policy: 'observe_only' }
    ], { placeHolder: 'Choose improvement mode' });
    if (!mode) return;

    outputChannel.show(true);
    const bar = createStatusBar('$(sync~spin) AI Improvement: observing project health...');
    try {
        const start = await apiFetch('POST', '/improvements/cycles', {
            project_name: workspace.name,
            policy: mode.policy,
            run_checks: true,
            pause_for_candidate_selection: mode.policy === 'manual',
            experiment_mode: false
        });
        lastImprovementCycleId = start.cycle_id;
        log(`[IMPROVEMENT] Cycle ${start.cycle_id} started (${mode.policy}).`);
        await consumeImprovementEventStream(start.cycle_id, bar);
        let cycle = await apiFetch('GET', `/improvements/cycles/${encodeURIComponent(start.cycle_id)}`);

        if (cycle.state === 'WAITING_SELECTION') {
            const eligible = (cycle.candidates || []).filter(c => !c.suppressed);
            if (!eligible.length) {
                await openMarkdown(`Improvement Cycle — ${workspace.name}`, renderImprovementCycle(cycle));
                return;
            }
            const picked = await vscode.window.showQuickPick(eligible.map(c => ({
                label: c.problem,
                description: `${c.risk} risk · score ${Number(c.priority_score || 0).toFixed(3)} · repeats ${c.repeat_count || 0}`,
                detail: c.proposal,
                candidate: c
            })), { placeHolder: 'Choose the candidate to validate' });
            if (!picked) {
                await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycle.id)}/cancel`, {});
                return;
            }
            const experiment = await vscode.window.showQuickPick([
                { label: 'Validate selected candidate', experiment: false, count: 1 },
                { label: 'Compare top 2 isolated candidates', experiment: true, count: 2 }
            ], { placeHolder: 'Validation mode' });
            if (!experiment) return;
            await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycle.id)}/select`, {
                candidate_id: picked.candidate.id,
                experiment_mode: experiment.experiment,
                experiment_candidates: experiment.count
            });
            bar.text = '$(sync~spin) AI Improvement: validating candidate...';
            await consumeImprovementEventStream(cycle.id, bar);
            cycle = await apiFetch('GET', `/improvements/cycles/${encodeURIComponent(cycle.id)}`);
        }

        if (cycle.state === 'WAITING_APPROVAL' && cycle.approval_status && !cycle.approval_status.passed) {
            const approverId = await vscode.window.showInputBox({ prompt: 'Verified approver ID', ignoreFocusOut: true });
            if (approverId) {
                const role = await vscode.window.showInputBox({ prompt: 'Approver role', value: (cycle.approval_status.required_roles || [])[0] || 'maintainer', ignoreFocusOut: true });
                const token = role ? await vscode.window.showInputBox({ prompt: 'Approval token (not stored by the backend)', password: true, ignoreFocusOut: true }) : null;
                if (role && token) {
                    await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycle.id)}/approve`, { approver_id: approverId, role, token });
                    cycle = await apiFetch('GET', `/improvements/cycles/${encodeURIComponent(cycle.id)}`);
                }
            }
        }

        await openMarkdown(`Improvement Cycle — ${workspace.name}`, renderImprovementCycle(cycle));
        if (cycle.state === 'WAITING_APPROVAL') {
            const decision = await vscode.window.showWarningMessage(
                'A verified improvement passed machine checks and governance. Apply the exact patch to the live project?',
                { modal: true }, 'Apply Verified Improvement', 'Keep for Later', 'Cancel Cycle'
            );
            if (decision === 'Apply Verified Improvement') {
                bar.text = '$(sync~spin) AI Improvement: applying verified candidate...';
                const applied = await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycle.id)}/apply`, { confirm: true });
                await openMarkdown(`Improvement Apply — ${workspace.name}`, renderImprovementCycle(applied));
            } else if (decision === 'Cancel Cycle') {
                await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycle.id)}/cancel`, {});
            }
        }
    } catch (err) {
        log(`[IMPROVEMENT ERROR] ${err.message}`);
        vscode.window.showErrorMessage(`Improvement cycle failed: ${err.message}`);
    } finally { bar.dispose(); }
}

async function consumeImprovementEventStream(cycleId, statusBar) {
    const response = await fetch(`${backendUrl()}/improvements/cycles/${encodeURIComponent(cycleId)}/events/stream`);
    if (!response.ok) throw new Error(`Improvement activity stream failed: HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            if (!block.trim() || block.startsWith(':')) continue;
            let eventType = 'message';
            let data = null;
            for (const line of block.split('\n')) {
                if (line.startsWith('event:')) eventType = line.slice(6).trim();
                if (line.startsWith('data:')) {
                    try { data = JSON.parse(line.slice(5).trim()); } catch (_) {}
                }
            }
            if (eventType === 'end') return;
            if (data) {
                const message = data.message || eventType.replace(/_/g, ' ');
                statusBar.text = `$(sync~spin) AI Improvement: ${message}`;
                log(`[IMPROVEMENT:${eventType.toUpperCase()}] ${message}`);
            }
        }
    }
}

async function showAutonomyReadiness() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const report = await apiFetch('GET', `/improvements/readiness?project_name=${encodeURIComponent(workspace.name)}`);
        await openMarkdown(`Autonomy Readiness — ${workspace.name}`, renderAutonomyReadiness(report));
    } catch (err) {
        vscode.window.showErrorMessage(`Autonomy readiness failed: ${err.message}`);
    }
}

async function showSchedulerStatus() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const report = await apiFetch('GET', `/improvements/scheduler/status?project_name=${encodeURIComponent(workspace.name)}`);
        await openMarkdown(`Dry-Run Scheduler — ${workspace.name}`, renderSchedulerStatus(report));
    } catch (err) {
        vscode.window.showErrorMessage(`Scheduler status failed: ${err.message}`);
    }
}

async function schedulerOperatorHeaders() {
    const state = await apiFetch('GET', '/improvements/scheduler/status');
    if (!state?.status?.operator_registry_configured) return {};
    const operatorId = await vscode.window.showInputBox({ prompt: 'Scheduler operator ID', ignoreFocusOut: true });
    if (!operatorId) return null;
    const token = await vscode.window.showInputBox({ prompt: 'Scheduler operator token', password: true, ignoreFocusOut: true });
    if (!token) return null;
    return {
        'X-Improvement-Operator-ID': operatorId,
        'X-Improvement-Operator-Token': token
    };
}

async function simulateSchedulerCommand() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const state = await apiFetch('GET', `/improvements/scheduler/status?project_name=${encodeURIComponent(workspace.name)}`);
        const schedules = state?.schedules || [];
        if (!schedules.length) {
            vscode.window.showInformationMessage('No scheduler definitions exist for this project.');
            return;
        }
        const picked = await vscode.window.showQuickPick(
            schedules.map(s => ({ label: s.name, description: `${s.environment || 'dev'} · ${s.mode} · every ${s.interval_minutes}m`, schedule: s })),
            { placeHolder: 'Select a dry-run schedule to simulate' }
        );
        if (!picked) return;
        const result = await apiFetch('GET', `/improvements/scheduler/schedules/${encodeURIComponent(picked.schedule.id)}/simulate`);
        const blockers = (result?.decision?.blockers || []).map(g => `- ❌ **${g.name}** — ${g.message || ''}`).join('\n') || '- ✅ All deterministic gates pass';
        await openMarkdown(`Scheduler Simulation — ${picked.label}`, `**Would run:** ${result.would_run ? 'yes' : 'no'}  \n**Source apply:** DISABLED\n\n${blockers}`);
    } catch (err) {
        vscode.window.showErrorMessage(`Scheduler simulation failed: ${err.message}`);
    }
}

async function showSchedulerMetrics() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [metrics, alerts] = await Promise.all([
            apiFetch('GET', `/improvements/scheduler/metrics?project_name=${encodeURIComponent(workspace.name)}`),
            apiFetch('GET', `/improvements/scheduler/alerts?project_name=${encodeURIComponent(workspace.name)}&status=open&limit=20`)
        ]);
        const alertRows = (alerts.alerts || []).map(a => `- **${a.severity} / ${a.code}** — ${a.message}`).join('\n') || '- No open alerts';
        await openMarkdown(`Scheduler Metrics — ${workspace.name}`, `## Metrics\n\n\`\`\`json\n${JSON.stringify(metrics, null, 2)}\n\`\`\`\n\n## Open Alerts\n\n${alertRows}`);
    } catch (err) {
        vscode.window.showErrorMessage(`Scheduler metrics failed: ${err.message}`);
    }
}

async function showSchedulerIntegrations() {
    try {
        const report = await apiFetch('GET', '/improvements/scheduler/integrations?limit=20');
        const deliveries = (report.deliveries || []).map(d => `- **${d.status}** · ${d.kind} · attempts ${d.attempts} · ${d.last_error || 'ok'}`).join('\n') || '- No integration deliveries';
        const publications = (report.status_publications || []).map(d => `- **${d.status}** · ${d.provider} · ${d.target}@${String(d.commit_sha || '').slice(0, 12)} · attempts ${d.attempts}`).join('\n') || '- No status publications';
        await openMarkdown('Scheduler Integrations', `## Integration Status\n\n\`\`\`json\n${JSON.stringify(report.status || {}, null, 2)}\n\`\`\`\n\n## Coordination\n\n\`\`\`json\n${JSON.stringify(report.coordination || {}, null, 2)}\n\`\`\`\n\n## Secret Provider\n\n\`\`\`json\n${JSON.stringify(report.secrets || {}, null, 2)}\n\`\`\`\n\n## Recent Deliveries\n\n${deliveries}\n\n## Commit Status Publications\n\n${publications}`);
    } catch (err) {
        vscode.window.showErrorMessage(`Scheduler integrations failed: ${err.message}`);
    }
}

async function runSchedulerDrDrill() {
    const decision = await vscode.window.showWarningMessage(
        'Run a scheduler disaster-recovery drill? This creates and verifies a database backup without restoring over the live database.',
        { modal: true }, 'Run DR Drill'
    );
    if (decision !== 'Run DR Drill') return;
    try {
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;
        const result = await apiFetch('POST', '/improvements/scheduler/admin/dr-drill', { confirm: true }, headers);
        const verification = await apiFetch('POST', `/improvements/scheduler/admin/dr-drills/${encodeURIComponent(result.id)}/verify-restore`, {}, headers);
        vscode.window.showInformationMessage(`DR drill ${result.status}: integrity ${result.integrity_check}; restore ${verification.verified ? 'verified' : 'FAILED'}`);
    } catch (err) {
        vscode.window.showErrorMessage(`DR drill failed: ${err.message}`);
    }
}


async function showSchedulerDeploymentHealth() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [ready, integrations, traces] = await Promise.all([
            apiFetch('GET', '/health/ready'),
            apiFetch('GET', '/improvements/scheduler/integrations?limit=10'),
            apiFetch('GET', `/improvements/scheduler/traces?project_name=${encodeURIComponent(workspace.name)}&limit=20`)
        ]);
        const traceRows = (traces.traces || []).map(t => `- **${t.name}** · ${t.status} · ${Number(t.duration_ms || 0).toFixed(1)} ms · run ${t.run_id || '-'}`).join('\n') || '- No scheduler traces yet';
        await openMarkdown(`Scheduler Deployment Health — ${workspace.name}`, `## Readiness\n\n\`\`\`json\n${JSON.stringify(ready, null, 2)}\n\`\`\`\n\n## Integration / HA Status\n\n\`\`\`json\n${JSON.stringify({ status: integrations.status, coordination: integrations.coordination, secrets: integrations.secrets }, null, 2)}\n\`\`\`\n\n## Recent Structured Traces\n\n${traceRows}\n\n**Scheduled source apply remains disabled.**`);
    } catch (err) {
        vscode.window.showErrorMessage(`Deployment health failed: ${err.message}`);
    }
}

async function showStagingReleaseCenter() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [caps, releaseData, cyclesData] = await Promise.all([
            apiFetch('GET', '/improvements/releases/capabilities'),
            apiFetch('GET', `/improvements/releases?project_name=${encodeURIComponent(workspace.name)}&limit=20`),
            apiFetch('GET', `/improvements/cycles?project_name=${encodeURIComponent(workspace.name)}&limit=20`)
        ]);
        const releases = releaseData.items || [];
        const rows = releases.map(r => `- **${r.status}** · ${r.id} · issue ${r.issue_id}${r.commit_sha ? ` · ${String(r.commit_sha).slice(0, 12)}` : ''}`).join('\n') || '- No staging release candidates';
        await openMarkdown(`Staging Release Center — ${workspace.name}`, `## Capabilities\n\n\`\`\`json\n${JSON.stringify(caps, null, 2)}\n\`\`\`\n\n## Recent Releases\n\n${rows}\n\n**Production promotion is not available from this control plane.**`);

        const actions = [{ label: '$(eye) View only', action: 'view' }];
        const latest = (cyclesData.cycles || []).find(c => c.state === 'WAITING_APPROVAL' && c.selected_issue_id);
        if (latest) actions.push({ label: '$(package) Create staging release from latest verified candidate', action: 'create', cycle: latest });
        if (releases.length) actions.push({ label: '$(run) Run release pipeline', action: 'run' });
        if (releases.some(r => r.status === 'waiting_staging_approval')) actions.push({ label: '$(check) Mark release staging-ready', action: 'promote' });
        const picked = await vscode.window.showQuickPick(actions, { placeHolder: 'Optional staging release action' });
        if (!picked || picked.action === 'view') return;
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;
        if (picked.action === 'create') {
            const created = await apiFetch('POST', '/improvements/releases', { project_name: workspace.name, issue_id: picked.cycle.selected_issue_id, require_preview: false }, headers);
            await apiFetch('POST', `/improvements/releases/${encodeURIComponent(created.id)}/run`, {}, headers);
            vscode.window.showInformationMessage(`Staging release ${created.id} created and pipeline started.`);
            return;
        }
        const eligible = releases.filter(r => picked.action === 'promote' ? r.status === 'waiting_staging_approval' : !['staging_ready','rejected'].includes(r.status));
        const selected = await vscode.window.showQuickPick(eligible.map(r => ({ label: r.status, description: r.id, release: r })), { placeHolder: 'Select release candidate' });
        if (!selected) return;
        if (picked.action === 'run') {
            await apiFetch('POST', `/improvements/releases/${encodeURIComponent(selected.release.id)}/run`, {}, headers);
            vscode.window.showInformationMessage(`Release pipeline ran for ${selected.release.id}.`);
        } else {
            await apiFetch('POST', `/improvements/releases/${encodeURIComponent(selected.release.id)}/promote-staging`, { confirm: true }, headers);
            vscode.window.showInformationMessage(`Release ${selected.release.id} is staging-ready. Production promotion remains unavailable.`);
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Staging release center failed: ${err.message}`);
    }
}


async function showStagingProviderCenter() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [caps, releaseData, requestData] = await Promise.all([
            apiFetch('GET', '/improvements/staging/capabilities'),
            apiFetch('GET', `/improvements/releases?project_name=${encodeURIComponent(workspace.name)}&limit=30`),
            apiFetch('GET', '/improvements/staging/production-release-requests?limit=30')
        ]);
        const releases = releaseData.items || [];
        const rows = releases.map(r => `- **${r.status}** · ${r.id} · issue ${r.issue_id}`).join('\n') || '- No releases';
        const requests = (requestData.items || []).map(r => `- **${r.status}** · ${r.id} · release ${r.release_id} · by ${r.requested_by}/${r.role}`).join('\n') || '- No production release requests';
        await openMarkdown(`Staging Providers — ${workspace.name}`, `## Part 13 Capabilities\n\n\`\`\`json\n${JSON.stringify(caps, null, 2)}\n\`\`\`\n\n## Releases\n\n${rows}\n\n## Production Release Handoffs\n\n${requests}\n\n**This control plane can deploy staging only. Production deployment is unsupported.**`);

        const actions = [{ label: '$(eye) View only', action: 'view' }];
        if (releases.some(r => r.status === 'staging_ready')) actions.push({ label: '$(cloud-upload) Register external staging deployment', action: 'deploy' });
        if (releases.some(r => r.status === 'staging_validated')) actions.push({ label: '$(package) Create production release request', action: 'request' });
        const picked = await vscode.window.showQuickPick(actions, { placeHolder: 'Optional Part 13 action' });
        if (!picked || picked.action === 'view') return;
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;
        const eligible = releases.filter(r => picked.action === 'deploy' ? r.status === 'staging_ready' : r.status === 'staging_validated');
        const selected = await vscode.window.showQuickPick(eligible.map(r => ({ label: r.status, description: r.id, release: r })), { placeHolder: 'Select release' });
        if (!selected) return;
        if (picked.action === 'deploy') {
            const previewUrl = await vscode.window.showInputBox({ prompt: 'HTTPS staging preview URL', placeHolder: 'https://staging.example.com/preview/...' });
            if (!previewUrl) return;
            const dep = await apiFetch('POST', `/improvements/staging/releases/${encodeURIComponent(selected.release.id)}/deployments`, { provider: 'external', preview_url: previewUrl }, headers);
            vscode.window.showInformationMessage(`Staging deployment ${dep.id} registered as ${dep.status}. Run staging tests through the API/dashboard before requesting production.`);
            return;
        }
        const confirm = await vscode.window.showWarningMessage('Create a human-authorized production release REQUEST? This does not deploy production.', { modal: true }, 'Create Request');
        if (confirm !== 'Create Request') return;
        const result = await apiFetch('POST', `/improvements/staging/releases/${encodeURIComponent(selected.release.id)}/production-release-request`, { confirm: true, notes: 'Requested from VS Code' }, headers);
        vscode.window.showInformationMessage(`Production release request ${result.request.id} created. No production deployment was executed.`);
    } catch (err) {
        vscode.window.showErrorMessage(`Staging provider center failed: ${err.message}`);
    }
}




async function showIntelligenceEfficiency() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [caps, efficiency, usage] = await Promise.all([
            apiFetch('GET', '/v1.1/capabilities'),
            apiFetch('GET', `/v1.1/evaluation/repair-efficiency?project_name=${encodeURIComponent(workspace.name)}&limit=500`),
            apiFetch('GET', '/v1.1/evaluation/model-usage?limit=1000')
        ]);
        const task = await vscode.window.showInputBox({
            prompt: 'Optional: preview the adaptive route for a coding task',
            placeHolder: 'e.g. Fix authentication timeout regression'
        });
        let route = null;
        if (task) {
            const ctx = editorContext(workspace);
            route = await apiFetch('POST', '/v1.1/routing/preview', { task, files: ctx.files || [], evidence: { diagnostics: ctx.diagnostics || [] } });
        }
        await openMarkdown(`Intelligence & Efficiency — ${workspace.name}`, `## v1.1 Intelligence & Efficiency\n\n**Adaptive routing:** ${caps.adaptive_agent_routing ? 'enabled' : 'disabled'}  \n**Repository graph context:** ${caps.repository_graph_context ? 'enabled' : 'disabled'}  \n**Contextual mistake memory:** ${caps.contextual_experience_memory ? 'enabled' : 'disabled'}  \n**Model-weight retraining:** ${caps.model_weight_retraining ? 'yes' : 'NO'}\n\n### Repair efficiency\n\n\`\`\`json\n${JSON.stringify(efficiency, null, 2)}\n\`\`\`\n\n### LLM usage telemetry\n\n\`\`\`json\n${JSON.stringify(usage, null, 2)}\n\`\`\`\n\n### Route preview\n\n${route ? `\`\`\`json\n${JSON.stringify(route, null, 2)}\n\`\`\`` : '_No task entered._'}\n\nUsage telemetry stores only sizes/durations and token estimates, not prompt or completion text.`);
    } catch (err) {
        vscode.window.showErrorMessage(`Could not load v1.1 intelligence metrics: ${err.message}`);
    }
}

async function showProductionCertification() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [caps, readiness, certs] = await Promise.all([
            apiFetch('GET', '/improvements/certification/capabilities'),
            apiFetch('GET', `/improvements/certification/readiness?project_name=${encodeURIComponent(workspace.name)}`),
            apiFetch('GET', `/improvements/certification/certificates?project_name=${encodeURIComponent(workspace.name)}&limit=20`)
        ]);
        const gateRows = (readiness.required_gates || []).map(g => `- ${g.passed ? '✅' : '❌'} **${g.gate}**${g.stale ? ' · stale' : ''}`).join('\n') || '- No gates configured';
        const certificateRows = (certs.items || []).map(c => `- **${c.verdict}** · ${c.id} · ${c.created_at || ''}`).join('\n') || '- No readiness certificates issued';
        await openMarkdown(`Production Readiness Certification — ${workspace.name}`, `## Part 16 Certification\n\n**Verdict:** ${readiness.verdict}  \n**Eligible:** ${readiness.eligible ? 'YES' : 'NO'}  \n**Certificate signing configured:** ${caps.signing_configured ? 'yes' : 'NO'}  \n**AI backend can deploy production:** ${readiness.backend_can_execute_production ? 'yes' : 'NO'}\n\n### Hardening gates\n\n${gateRows}\n\n### Blockers\n\n\`\`\`json\n${JSON.stringify(readiness.blockers || [], null, 2)}\n\`\`\`\n\n### Production history\n\n\`\`\`json\n${JSON.stringify(readiness.production_history || {}, null, 2)}\n\`\`\`\n\n### Certificates\n\n${certificateRows}\n\nPart 16 certification records verified operational evidence; it does **not** grant the AI backend production credentials or deployment authority.`);
    } catch (err) {
        vscode.window.showErrorMessage(`Could not load production certification: ${err.message}`);
    }
}

async function showProductionLearning() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [learning, outcomes] = await Promise.all([
            apiFetch('GET', `/improvements/production-outcomes/learning?project_name=${encodeURIComponent(workspace.name)}`),
            apiFetch('GET', `/improvements/production-outcomes?project_name=${encodeURIComponent(workspace.name)}&limit=30`)
        ]);
        const rows = (outcomes.items || []).map(o => `- **${o.status}** · ${o.rollout_strategy || 'unknown'} · ${o.provider || 'unknown'} · ${o.failure_class || 'no failure'} · ${o.created_at || ''}`).join('\n') || '- No production outcomes have been ingested yet.';
        await openMarkdown(`Production Outcome Learning — ${workspace.name}`, `## Part 15 Operational Learning\n\n**Type:** ${learning.learning_type || 'persisted operational outcome memory'}  \n**Sampled outcomes:** ${learning.outcomes_sampled || 0}  \n**Succeeded:** ${learning.succeeded || 0}  \n**Failed:** ${learning.failed || 0}  \n**Rolled back:** ${learning.rolled_back || 0}  \n**AI backend can deploy production:** ${learning.backend_can_execute_production ? 'yes' : 'NO'}\n\n### Strategy learning\n\n\`\`\`json\n${JSON.stringify(learning.strategies || [], null, 2)}\n\`\`\`\n\n### Recent signed production outcomes\n\n${rows}\n\nProduction failures and rollbacks influence future strategy ranking and risk. This is operational memory, **not model-weight retraining**.`);
    } catch (err) {
        vscode.window.showErrorMessage(`Could not load production learning: ${err.message}`);
    }
}

async function showProductionGovernanceCenter() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const [caps, casesData, requestData, releaseData, packageData] = await Promise.all([
            apiFetch('GET', '/improvements/production-governance/capabilities'),
            apiFetch('GET', `/improvements/production-governance/cases?project_name=${encodeURIComponent(workspace.name)}&limit=30`),
            apiFetch('GET', '/improvements/staging/production-release-requests?limit=50'),
            apiFetch('GET', `/improvements/releases?project_name=${encodeURIComponent(workspace.name)}&limit=50`),
            apiFetch('GET', '/improvements/production-governance/packages?limit=100')
        ]);
        const cases = casesData.items || [];
        const releaseIds = new Set((releaseData.items || []).map(r => r.id));
        const requests = (requestData.items || []).filter(r => releaseIds.has(r.release_id));
        const packages = (packageData.items || []).filter(p => (p.payload || {}).project_name === workspace.name);
        const caseRows = cases.map(c => `- **${c.status}** · ${c.id} · release ${c.release_id}${c.locked_at ? ' · LOCKED' : ''}`).join('\n') || '- No governance cases';
        const reqRows = requests.map(r => `- **${r.status}** · ${r.id} · release ${r.release_id}`).join('\n') || '- No production release requests';
        await openMarkdown(`Production Governance — ${workspace.name}`, `## Part 14/15 Capabilities\n\n\`\`\`json\n${JSON.stringify(caps, null, 2)}\n\`\`\`\n\n## Production Release Requests\n\n${reqRows}\n\n## Governance Cases\n\n${caseRows}\n\n**This backend signs credential-free packages and short-lived deployment authorizations only. Production execution happens in the separate Part 15 deployer service.**`);

        const actions = [{ label: '$(eye) View only', action: 'view' }];
        if (requests.some(r => !cases.some(c => c.production_request_id === r.id))) actions.push({ label: '$(new-file) Open governance case', action: 'create' });
        if (cases.some(c => !c.locked_at && c.status !== 'rejected')) {
            actions.push({ label: '$(edit) Set ticket + rollout + immutable artifact', action: 'configure' });
            actions.push({ label: '$(check) Submit approval', action: 'approve' });
            actions.push({ label: '$(lock) Lock approved governance case', action: 'lock' });
        }
        if (cases.some(c => c.locked_at && c.status !== 'packaged')) actions.push({ label: '$(package) Create signed deployer package', action: 'package' });
        if (packages.length) actions.push({ label: '$(key) Issue short-lived deployment authorization', action: 'authorize' });
        const picked = await vscode.window.showQuickPick(actions, { placeHolder: 'Optional Part 14 governance action' });
        if (!picked || picked.action === 'view') return;
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;

        if (picked.action === 'create') {
            const eligible = requests.filter(r => !cases.some(c => c.production_request_id === r.id));
            const selected = await vscode.window.showQuickPick(eligible.map(r => ({ label: r.id, description: `release ${r.release_id}`, request: r })), { placeHolder: 'Select production release request' });
            if (!selected) return;
            const result = await apiFetch('POST', '/improvements/production-governance/cases', { production_request_id: selected.request.id }, headers);
            vscode.window.showInformationMessage(`Governance case ${result.id} created.`);
            return;
        }

        if (picked.action === 'authorize') {
            const selectedPackage = await vscode.window.showQuickPick(packages.map(p => ({ label: p.id, description: `${(p.payload || {}).artifact_binding?.artifact_ref || 'artifact not bound'}`, item: p })), { placeHolder: 'Select signed package to authorize' });
            if (!selectedPackage) return;
            const confirm = await vscode.window.showWarningMessage('Issue a short-lived, single-use deployment authorization for the independent production deployer? This does not deploy production.', { modal: true }, 'Issue Authorization');
            if (confirm !== 'Issue Authorization') return;
            const result = await apiFetch('POST', `/improvements/production-governance/packages/${encodeURIComponent(selectedPackage.item.id)}/deployment-authorization`, { confirm: true }, headers);
            vscode.window.showInformationMessage(`Deployment authorization ${result.authorization.id} issued. No production deployment was executed.`);
            return;
        }

        const eligibleCases = cases.filter(c => picked.action === 'package' ? (c.locked_at && c.status !== 'packaged') : (!c.locked_at && c.status !== 'rejected'));
        const selected = await vscode.window.showQuickPick(eligibleCases.map(c => ({ label: c.status, description: c.id, item: c })), { placeHolder: 'Select governance case' });
        if (!selected) return;
        const id = encodeURIComponent(selected.item.id);
        if (picked.action === 'configure') {
            const ticket = await vscode.window.showInputBox({ prompt: 'Change ticket reference', placeHolder: 'REL-140', ignoreFocusOut: true });
            if (!ticket) return;
            const strategy = await vscode.window.showQuickPick(['canary', 'blue_green', 'rolling'], { placeHolder: 'Production rollout strategy' });
            if (!strategy) return;
            const artifactKind = await vscode.window.showQuickPick(['oci_image', 'ecs_task_definition', 'generic_immutable_artifact'], { placeHolder: 'Immutable production artifact type' });
            if (!artifactKind) return;
            const artifactRef = await vscode.window.showInputBox({ prompt: 'Immutable production artifact reference', placeHolder: 'ghcr.io/acme/app@sha256:...' });
            if (!artifactRef) return;
            const artifactDigest = await vscode.window.showInputBox({ prompt: 'Exact artifact SHA-256 digest (64 hex characters)', validateInput: value => /^[a-fA-F0-9]{64}$/.test(value.trim()) ? undefined : 'Enter exactly 64 hexadecimal characters' });
            if (!artifactDigest) return;
            await apiFetch('POST', `/improvements/production-governance/cases/${id}/change-ticket`, { system: 'jira', reference: ticket }, headers);
            await apiFetch('POST', `/improvements/production-governance/cases/${id}/rollout-plan`, { strategy }, headers);
            await apiFetch('POST', `/improvements/production-governance/cases/${id}/artifact-binding`, { kind: artifactKind, artifact_ref: artifactRef, digest_sha256: artifactDigest.trim().toLowerCase() }, headers);
            vscode.window.showInformationMessage('Governance evidence and exact artifact binding updated. Older approvals no longer count.');
        } else if (picked.action === 'approve') {
            await apiFetch('POST', `/improvements/production-governance/cases/${id}/approvals`, { decision: 'approve', comment: 'Approved from VS Code' }, headers);
            vscode.window.showInformationMessage('Evidence-bound governance approval recorded.');
        } else if (picked.action === 'lock') {
            const confirm = await vscode.window.showWarningMessage('Lock the exact governance evidence? Change ticket, train and rollout inputs become immutable.', { modal: true }, 'Lock Evidence');
            if (confirm !== 'Lock Evidence') return;
            await apiFetch('POST', `/improvements/production-governance/cases/${id}/lock`, { confirm: true }, headers);
            vscode.window.showInformationMessage('Governance case locked with signed evidence.');
        } else if (picked.action === 'package') {
            const confirm = await vscode.window.showWarningMessage('Create a signed credential-free package for an independent production deployer?', { modal: true }, 'Create Package');
            if (confirm !== 'Create Package') return;
            const result = await apiFetch('POST', `/improvements/production-governance/cases/${id}/deployment-package`, { confirm: true }, headers);
            vscode.window.showInformationMessage(`Deployment package ${result.package.id} created. No production deployment was executed.`);
        }
    } catch (err) {
        vscode.window.showErrorMessage(`Production governance failed: ${err.message}`);
    }
}

async function runSchedulerTickCommand() {
    const decision = await vscode.window.showWarningMessage(
        'Run all due dry-run schedules now? Scheduled source apply is disabled.',
        { modal: true }, 'Run Due Dry-Runs'
    );
    if (decision !== 'Run Due Dry-Runs') return;
    try {
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;
        const result = await apiFetch('POST', '/improvements/scheduler/tick?limit=20', {}, headers);
        vscode.window.showInformationMessage(`Dry-run scheduler processed ${result.due || 0} due schedule(s).`);
        const workspace = getWorkspace();
        if (workspace) await showSchedulerStatus();
    } catch (err) {
        vscode.window.showErrorMessage(`Scheduler tick failed: ${err.message}`);
    }
}

async function schedulerEmergencyStop() {
    const state = await apiFetch('GET', '/improvements/scheduler/status');
    const active = !!state?.status?.kill_switch;
    const action = active ? 'Clear Emergency Stop' : 'Activate Emergency Stop';
    const decision = await vscode.window.showWarningMessage(
        `${action}? This controls dry-run scheduling only and does not alter the manual approval boundary.`,
        { modal: true }, action
    );
    if (decision !== action) return;
    try {
        const headers = await schedulerOperatorHeaders();
        if (headers === null) return;
        await apiFetch('POST', '/improvements/scheduler/kill-switch', {
            enabled: !active,
            reason: active ? 'Cleared from VS Code' : 'Emergency stop from VS Code',
            scope: 'global',
            confirm: true
        }, headers);
        vscode.window.showInformationMessage(active ? 'Scheduler emergency stop cleared.' : 'Scheduler emergency stop activated.');
    } catch (err) {
        vscode.window.showErrorMessage(`Could not change scheduler kill switch: ${err.message}`);
    }
}

async function cancelImprovementCycle() {
    let cycleId = lastImprovementCycleId;
    if (!cycleId) {
        cycleId = await vscode.window.showInputBox({ prompt: 'Improvement cycle ID to cancel' });
        if (!cycleId) return;
    }
    try {
        const result = await apiFetch('POST', `/improvements/cycles/${encodeURIComponent(cycleId.trim())}/cancel`, {});
        vscode.window.showInformationMessage(`Improvement cycle: ${result.state || result.status}`);
    } catch (err) {
        vscode.window.showErrorMessage(`Could not cancel improvement cycle: ${err.message}`);
    }
}

function renderImprovementCenter(health, cycles, policy, readiness, scheduler) {
    const dimensions = Object.entries(health.dimensions || {}).map(([name, score]) => `- **${name}:** ${score}`).join('\n') || '- None';
    const rows = cycles.map(c => `- **${c.state}** — ${c.id} — ${c.started_at}`).join('\n') || '- No cycles yet';
    return `## Health\n\n**Score:** ${health.health_score ?? 'n/a'}\n\n${dimensions}\n\n${renderAutonomyReadiness(readiness)}\n\n${renderSchedulerStatus(scheduler)}\n\n## Active Policy\n\nVersion ${policy.version || 0} (${policy.source || 'defaults'})\n\n\`\`\`json\n${JSON.stringify(policy.policy || {}, null, 2)}\n\`\`\`\n\n## Recent Cycles\n\n${rows}`;
}

function renderAutonomyReadiness(report) {
    const gates = (report?.gates || []).map(g => `- ${g.passed ? '✅' : '❌'} **${g.name}** — ${g.message || ''}`).join('\n') || '- No readiness evidence';
    return `## Autonomy Readiness\n\n**Verdict:** ${report?.verdict || 'unknown'}  \n**Scheduler enabled:** ${report?.scheduler_enabled ? 'yes' : 'no'}  \n**Automatic source apply:** ${report?.automatic_source_apply_enabled ? 'yes' : 'no'}\n\n${gates}`;
}

function renderSchedulerStatus(report) {
    const status = report?.status || {};
    const schedules = (report?.schedules || []).map(s => `- **${s.name}** · ${s.environment || 'dev'} · ${s.mode} · every ${s.interval_minutes}m · ${s.enabled ? 'enabled' : 'disabled'} · next ${s.next_run_at || 'now'}`).join('\n') || '- No schedules';
    const runs = (report?.recent_runs || []).slice(0, 10).map(r => `- **${r.status}** · ${r.mode} · ${r.started_at} · cycle ${r.cycle_id || 'none'}`).join('\n') || '- No scheduler runs';
    return `## Dry-Run Scheduler\n\n**Background polling:** ${status.background_scheduler_enabled ? 'enabled' : 'disabled'}  \n**Kill switch:** ${status.kill_switch ? 'ACTIVE' : 'clear'}  \n**Scheduled source apply:** ${status.scheduled_source_apply_enabled ? 'enabled' : 'DISABLED'}  \n**Signed webhooks:** ${status.signed_webhook_configured ? 'configured' : 'not configured'}  \n**Operator registry:** ${status.operator_registry_configured ? 'configured' : 'not configured'}  \n**Lease backend:** ${status.coordination?.lease_backend || 'sqlite'}  \n**Leader election:** ${status.coordination?.leader_election_enabled ? 'enabled' : 'disabled'}  \n**Alert sink:** ${status.integrations?.alert_webhook_configured ? 'configured' : 'off'}  \n**OTEL export:** ${status.integrations?.otel_export_configured ? 'configured' : 'off'}\n\n### Schedules\n\n${schedules}\n\n### Recent Runs\n\n${runs}`;
}

function renderImprovementCycle(cycle) {
    const candidates = (cycle.candidates || []).map(c => `- **${c.status}** · ${c.risk} · ${Number(c.priority_score || 0).toFixed(3)} — ${c.problem}${c.suppressed ? ` _(suppressed: ${c.suppression_reason})_` : ''}`).join('\n') || '- None';
    const experiments = (cycle.experiments || []).map(e => `- #${e.experiment_rank} **${e.status}** · quality ${e.quality_score ?? 'n/a'} · ${e.candidate_id}`).join('\n') || '- None';
    const governance = cycle.result?.governance ? `\n\n## Governance\n\n\`\`\`json\n${JSON.stringify(cycle.result.governance, null, 2)}\n\`\`\`` : '';
    const approval = cycle.approval_status ? `\n\n## Approval Evidence\n\n${cycle.approval_status.verified_approvals}/${cycle.approval_status.minimum} verified approvals · roles: ${(cycle.approval_status.verified_roles || []).join(', ') || 'none'}` : '';
    const integrity = cycle.policy_integrity_status ? `\n\n**Policy integrity:** ${cycle.policy_integrity_status.passed ? 'verified' : 'FAILED'} (${cycle.policy_integrity_status.algorithm})` : '';
    return `**State:** ${cycle.state || 'unknown'}  \n**Cycle:** ${cycle.id || ''}  \n**Baseline:** ${cycle.baseline_score ?? 'n/a'}  \n**Final:** ${cycle.final_score ?? 'n/a'}${integrity}\n\n## Candidates\n\n${candidates}\n\n## Experiments\n\n${experiments}${approval}${governance}`;
}

// ---- Existing audit tools --------------------------------------------------
async function runAudit() {
    const workspace = getWorkspace();
    if (!workspace) return;
    outputChannel.show(true);
    const bar = createStatusBar('$(sync~spin) AI Auditor: running...');
    try {
        const result = await apiFetch('POST', '/projects/audit/run', { project_name: workspace.name });
        log(`[AUDIT] ${result.overall_status || result.status}`);
        const report = path.join(workspace.root, 'AUDIT_REPORT.md');
        if (fs.existsSync(report)) await openFile(report);
    } catch (err) {
        vscode.window.showErrorMessage(`Audit failed: ${err.message}`);
    } finally { bar.dispose(); }
}

async function showAuditHistory() {
    const workspace = getWorkspace();
    if (!workspace) return;
    try {
        const data = await apiFetch('GET', `/projects/audit/reports?project_name=${encodeURIComponent(workspace.name)}`);
        const reports = data.reports || [];
        if (!reports.length) return vscode.window.showInformationMessage('No audit history found.');
        const selected = await vscode.window.showQuickPick(reports.map(r => ({
            label: `${r.overall_status === 'critical' ? '$(error)' : '$(check)'} ${new Date(r.created_at).toLocaleString()}`,
            description: r.overall_status,
            detail: r.id
        })));
        if (selected) vscode.window.showInformationMessage(`Audit ${selected.detail}: ${selected.description}`);
    } catch (err) { vscode.window.showErrorMessage(`History failed: ${err.message}`); }
}

async function runSecurityScan() {
    const workspace = getWorkspace();
    if (!workspace) return;
    outputChannel.show(true);
    const bar = createStatusBar('$(sync~spin) AI Auditor: security scan...');
    try {
        const start = await apiFetch('POST', `/projects/${encodeURIComponent(workspace.name)}/vulnerability_scan`, { target_url: null, db_url: null });
        if (start.status !== 'started') throw new Error(start.message || 'Scan did not start');
        log(`[SECURITY] Started session ${start.session_id}. Open the dashboard for full hybrid-scan progress.`);
        vscode.window.showInformationMessage(`Security scan started: ${start.session_id}`);
    } catch (err) { vscode.window.showErrorMessage(`Security scan failed: ${err.message}`); }
    finally { bar.dispose(); }
}

// ---- Helpers ---------------------------------------------------------------
function log(message) {
    outputChannel.appendLine(`[${new Date().toLocaleTimeString()}] ${message}`);
}
function createStatusBar(text) {
    const bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    bar.text = text; bar.show(); return bar;
}
function capitalize(value) { return value ? value[0].toUpperCase() + value.slice(1) : value; }
async function openFile(filePath, column = vscode.ViewColumn.Active) {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
    await vscode.window.showTextDocument(doc, column);
}
async function openFileAtLine(filePath, line) {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
    const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.Active);
    const safeLine = Math.max(0, Math.min((line || 1) - 1, Math.max(0, doc.lineCount - 1)));
    const position = new vscode.Position(safeLine, 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
}
async function apiFetch(method, route, body = null, extraHeaders = {}) {
    const options = { method, headers: { 'Content-Type': 'application/json', ...extraHeaders } };
    if (body !== null) options.body = JSON.stringify(body);
    const response = await fetch(`${backendUrl()}${route}`, options);
    if (!response.ok) {
        let detail = '';
        try { detail = (await response.json()).detail || ''; } catch (_) {}
        throw new Error(`Backend HTTP ${response.status}${detail ? `: ${detail}` : ''}`);
    }
    return response.json();
}
function deactivate() {}
module.exports = { activate, deactivate };
