import React, { useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';

const box = { border: '1px solid #30363d', borderRadius: 8, padding: 16, background: '#161b22' };
const button = { border: '1px solid #30363d', borderRadius: 6, padding: '7px 12px', background: '#21262d', color: '#e6edf3', cursor: 'pointer' };
const primaryButton = { ...button, borderColor: '#1f6feb', background: '#1f6feb' };

function scoreTone(score) {
  if (score >= 90) return '#3fb950';
  if (score >= 75) return '#d29922';
  return '#f85149';
}

export default function ImprovementCenterPanel({ projectName }) {
  const [health, setHealth] = useState(null);
  const [cycles, setCycles] = useState([]);
  const [policyRecord, setPolicyRecord] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [schedulerState, setSchedulerState] = useState(null);
  const [schedulerMetrics, setSchedulerMetrics] = useState(null);
  const [schedulerAlerts, setSchedulerAlerts] = useState([]);
  const [schedulerIntegrations, setSchedulerIntegrations] = useState(null);
  const [schedulerEnvironment, setSchedulerEnvironment] = useState('dev');
  const [schedulerPreview, setSchedulerPreview] = useState(null);
  const [releaseCapabilities, setReleaseCapabilities] = useState(null);
  const [stagingCapabilities, setStagingCapabilities] = useState(null);
  const [governanceCapabilities, setGovernanceCapabilities] = useState(null);
  const [governanceCases, setGovernanceCases] = useState([]);
  const [deploymentPackages, setDeploymentPackages] = useState([]);
  const [deploymentAuthorizations, setDeploymentAuthorizations] = useState([]);
  const [productionLearning, setProductionLearning] = useState(null);
  const [productionRequests, setProductionRequests] = useState([]);
  const [releases, setReleases] = useState([]);
  const [operatorId, setOperatorId] = useState(() => localStorage.getItem('improvement_operator_id') || '');
  const [operatorToken, setOperatorToken] = useState('');
  const [scheduleInterval, setScheduleInterval] = useState('1440');
  const [scheduleMode, setScheduleMode] = useState('observe_propose');
  const [approverId, setApproverId] = useState('');
  const [approverRole, setApproverRole] = useState('maintainer');
  const [approverToken, setApproverToken] = useState('');
  const [policyText, setPolicyText] = useState('');
  const [selectedCycle, setSelectedCycle] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const encoded = encodeURIComponent(projectName);
  const candidates = selectedCycle?.candidates || [];
  const selectableCandidates = useMemo(() => candidates.filter(item => !item.suppressed), [candidates]);

  async function refresh(loadHealth = true) {
    setError('');
    try {
      const requests = [
        apiClient.getJson(`/improvements/cycles?project_name=${encoded}&limit=20`),
        apiClient.getJson(`/improvements/policies/${encoded}`),
        apiClient.getJson(`/improvements/readiness?project_name=${encoded}`),
        apiClient.getJson(`/improvements/scheduler/status?project_name=${encoded}`),
        apiClient.getJson(`/improvements/scheduler/metrics?project_name=${encoded}`),
        apiClient.getJson(`/improvements/scheduler/alerts?project_name=${encoded}&status=open&limit=10`),
        apiClient.getJson('/improvements/scheduler/integrations?limit=10'),
        apiClient.getJson('/improvements/releases/capabilities'),
        apiClient.getJson(`/improvements/releases?project_name=${encoded}&limit=10`),
        apiClient.getJson('/improvements/staging/capabilities'),
        apiClient.getJson('/improvements/production-governance/capabilities'),
        apiClient.getJson(`/improvements/production-governance/cases?project_name=${encoded}&limit=20`),
        apiClient.getJson('/improvements/staging/production-release-requests?limit=50'),
        apiClient.getJson('/improvements/production-governance/packages?limit=100'),
        apiClient.getJson('/improvements/production-governance/deployment-authorizations?limit=100'),
        apiClient.getJson(`/improvements/production-outcomes/learning?project_name=${encoded}`),
      ];
      if (loadHealth) requests.push(apiClient.getJson(`/improvements/health?project_name=${encoded}&run_checks=false`));
      const [cycleData, policyData, readinessData, schedulerData, metricsData, alertsData, integrationsData, releaseCapsData, releasesData, stagingCapsData, governanceCapsData, governanceCasesData, productionRequestsData, packageData, authorizationData, productionLearningData, healthData] = await Promise.all(requests);
      setCycles(cycleData.cycles || []);
      setPolicyRecord(policyData);
      setReadiness(readinessData);
      setSchedulerState(schedulerData);
      setSchedulerMetrics(metricsData);
      setSchedulerAlerts(alertsData.alerts || []);
      setSchedulerIntegrations(integrationsData);
      setReleaseCapabilities(releaseCapsData);
      setReleases(releasesData.items || []);
      setStagingCapabilities(stagingCapsData);
      setGovernanceCapabilities(governanceCapsData);
      setGovernanceCases(governanceCasesData.items || []);
      setDeploymentPackages((packageData.items || []).filter(item => (item.payload || {}).project_name === projectName));
      setDeploymentAuthorizations(authorizationData.items || []);
      setProductionLearning(productionLearningData);
      const releaseIds = new Set((releasesData.items || []).map(r => r.id));
      setProductionRequests((productionRequestsData.items || []).filter(r => releaseIds.has(r.release_id)));
      setPolicyText(JSON.stringify(policyData.policy || {}, null, 2));
      if (healthData) setHealth(healthData);
      if (selectedCycle?.id) await openCycle(selectedCycle.id, false);
    } catch (err) {
      setError(err.message);
    }
  }

  async function openCycle(id, showBusy = true) {
    if (showBusy) setBusy('cycle');
    try {
      const data = await apiClient.getJson(`/improvements/cycles/${encodeURIComponent(id)}`);
      setSelectedCycle(data);
    } catch (err) {
      setError(err.message);
    } finally {
      if (showBusy) setBusy('');
    }
  }

  async function startCycle(observeOnly = false) {
    setBusy('start'); setError('');
    try {
      const data = await apiClient.postJson('/improvements/cycles', {
        project_name: projectName,
        policy: observeOnly ? 'observe_only' : 'manual',
        run_checks: true,
        pause_for_candidate_selection: !observeOnly,
        experiment_mode: false,
      });
      await openCycle(data.cycle_id, false);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function chooseCandidate(candidateId, experimentMode = false) {
    setBusy('select'); setError('');
    try {
      await apiClient.postJson(`/improvements/cycles/${selectedCycle.id}/select`, {
        candidate_id: candidateId,
        experiment_mode: experimentMode,
        experiment_candidates: experimentMode ? 2 : 1,
      });
      setTimeout(() => openCycle(selectedCycle.id, false), 500);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function approveCycle() {
    setBusy('approve'); setError('');
    try {
      await apiClient.postJson(`/improvements/cycles/${selectedCycle.id}/approve`, {
        approver_id: approverId, role: approverRole, token: approverToken,
      });
      setApproverToken('');
      await openCycle(selectedCycle.id, false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function applyCycle() {
    setBusy('apply'); setError('');
    try {
      await apiClient.postJson(`/improvements/cycles/${selectedCycle.id}/apply`, { confirm: true });
      await openCycle(selectedCycle.id, false);
      await refresh(true);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function cancelCycle() {
    setBusy('cancel'); setError('');
    try {
      await apiClient.postJson(`/improvements/cycles/${selectedCycle.id}/cancel`, {});
      await openCycle(selectedCycle.id, false);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function discardExperiment(experimentId) {
    setBusy('discard'); setError('');
    try {
      await apiClient.postJson(`/improvements/cycles/${selectedCycle.id}/experiments/${experimentId}/discard`, {});
      await openCycle(selectedCycle.id, false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function savePolicy() {
    setBusy('policy'); setError('');
    try {
      const parsed = JSON.parse(policyText);
      const saved = await apiClient.postJson(`/improvements/policies/${encoded}`, { policy: parsed, activate: true }, 'PUT');
      setPolicyRecord({ ...saved, policy: saved.policy || parsed });
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function approveBaseline() {
    setBusy('baseline'); setError('');
    try {
      await apiClient.postJson('/improvements/baselines', { project_name: projectName, label: 'approved-from-dashboard', activate: true });
      await refresh(true);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  function schedulerHeaders() {
    if (!operatorId || !operatorToken) return {};
    localStorage.setItem('improvement_operator_id', operatorId);
    return {
      'X-Improvement-Operator-ID': operatorId,
      'X-Improvement-Operator-Token': operatorToken,
    };
  }

  function schedulerPayload() {
    const hardened = schedulerEnvironment !== 'dev';
    const prod = schedulerEnvironment === 'prod';
    return {
      project_name: projectName,
      name: `${schedulerEnvironment.toUpperCase()} ${scheduleMode === 'canary_observe' ? 'Canary' : 'Observe'} schedule`,
      interval_minutes: Number(scheduleInterval || 1440),
      timezone: 'UTC',
      maintenance_windows: [],
      mode: scheduleMode,
      environment: schedulerEnvironment,
      enabled: true,
      require_readiness: true,
      require_ci_success: hardened,
      require_slo: prod,
      bind_ci_to_project_head: hardened,
      request: { run_checks: scheduleMode !== 'canary_observe' },
    };
  }

  async function previewDryRunSchedule() {
    setBusy('preview'); setError('');
    try {
      const preview = await apiClient.postJson('/improvements/scheduler/simulate', schedulerPayload());
      setSchedulerPreview(preview);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function createDryRunSchedule() {
    setBusy('schedule'); setError('');
    try {
      await apiClient.postJson('/improvements/scheduler/schedules', schedulerPayload(), 'POST', schedulerHeaders());
      setSchedulerPreview(null);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function runSchedulerTick() {
    setBusy('tick'); setError('');
    try {
      await apiClient.postJson('/improvements/scheduler/tick?limit=20', {}, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function toggleKillSwitch() {
    const active = !!schedulerState?.status?.kill_switch;
    setBusy('kill'); setError('');
    try {
      await apiClient.postJson('/improvements/scheduler/kill-switch', {
        enabled: !active,
        reason: active ? 'Cleared from dashboard' : 'Emergency stop from dashboard',
        scope: 'global',
        confirm: true,
      }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function flushSchedulerIntegrations() {
    setBusy('integrations'); setError('');
    try {
      await apiClient.postJson('/improvements/scheduler/integrations/flush', { limit: 100 }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function createStagingRelease() {
    if (!selectedCycle?.selected_issue_id) return;
    setBusy('release'); setError('');
    try {
      const release = await apiClient.postJson('/improvements/releases', {
        project_name: projectName, issue_id: selectedCycle.selected_issue_id, require_preview: false,
      }, 'POST', schedulerHeaders());
      await apiClient.postJson(`/improvements/releases/${encodeURIComponent(release.id)}/run`, {}, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function runStagingRelease(releaseId) {
    setBusy('release'); setError('');
    try {
      await apiClient.postJson(`/improvements/releases/${encodeURIComponent(releaseId)}/run`, {}, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function promoteStagingRelease(releaseId) {
    setBusy('release'); setError('');
    try {
      await apiClient.postJson(`/improvements/releases/${encodeURIComponent(releaseId)}/promote-staging`, { confirm: true }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function registerExternalStaging(releaseId) {
    const previewUrl = window.prompt('HTTPS staging preview URL');
    if (!previewUrl) return;
    setBusy('staging'); setError('');
    try {
      await apiClient.postJson(`/improvements/staging/releases/${encodeURIComponent(releaseId)}/deployments`, { provider: 'external', preview_url: previewUrl }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function createProductionReleaseRequest(releaseId) {
    if (!window.confirm('Create a human-authorized production release REQUEST? This does not deploy production.')) return;
    setBusy('release-request'); setError('');
    try {
      const result = await apiClient.postJson(`/improvements/staging/releases/${encodeURIComponent(releaseId)}/production-release-request`, { confirm: true, notes: 'Requested from dashboard' }, 'POST', schedulerHeaders());
      window.alert(`Release request ${result.request?.id || ''} created. No production deployment was executed.`);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function createGovernanceCase(requestId) {
    setBusy('governance'); setError('');
    try {
      await apiClient.postJson('/improvements/production-governance/cases', { production_request_id: requestId }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function configureGovernanceCase(caseId) {
    const reference = window.prompt('Change ticket reference (for example REL-140)');
    if (!reference) return;
    const strategy = window.prompt('Rollout strategy: canary, blue_green, or rolling', 'canary') || 'canary';
    const artifactKind = window.prompt('Artifact kind: oci_image, ecs_task_definition, or generic_immutable_artifact', 'oci_image') || 'oci_image';
    const artifactRef = window.prompt('Immutable production artifact reference (prefer digest-pinned OCI reference)');
    if (!artifactRef) return;
    const digest = window.prompt('Exact artifact SHA-256 digest (64 hex characters)');
    if (!digest || !/^[a-fA-F0-9]{64}$/.test(digest.trim())) { setError('Artifact digest must be exactly 64 hexadecimal characters.'); return; }
    setBusy('governance'); setError('');
    try {
      await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/change-ticket`, { system: 'jira', reference }, 'POST', schedulerHeaders());
      await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/rollout-plan`, { strategy }, 'POST', schedulerHeaders());
      await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/artifact-binding`, { kind: artifactKind, artifact_ref: artifactRef, digest_sha256: digest.trim().toLowerCase() }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function approveGovernanceCase(caseId) {
    setBusy('governance'); setError('');
    try {
      await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/approvals`, { decision: 'approve', comment: 'Approved from dashboard' }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function lockGovernanceCase(caseId) {
    if (!window.confirm('Lock this exact governance evidence? Inputs become immutable.')) return;
    setBusy('governance'); setError('');
    try {
      await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/lock`, { confirm: true }, 'POST', schedulerHeaders());
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function packageGovernanceCase(caseId) {
    if (!window.confirm('Create the signed credential-free package for the independent production deployer?')) return;
    setBusy('governance'); setError('');
    try {
      const result = await apiClient.postJson(`/improvements/production-governance/cases/${encodeURIComponent(caseId)}/deployment-package`, { confirm: true }, 'POST', schedulerHeaders());
      window.alert(`Signed deployment package ${result.package?.id || ''} created. This backend did not deploy production.`);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }


  async function issueDeploymentAuthorization(packageId) {
    if (!window.confirm('Issue a short-lived single-use authorization for the independent production deployer? This does not deploy production.')) return;
    setBusy('governance'); setError('');
    try {
      const result = await apiClient.postJson(`/improvements/production-governance/packages/${encodeURIComponent(packageId)}/deployment-authorization`, { confirm: true }, 'POST', schedulerHeaders());
      window.alert(`Authorization ${result.authorization?.id || ''} issued. Production execution remains outside this backend.`);
      await refresh(false);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  async function runDisasterRecoveryDrill() {
    setBusy('drill'); setError('');
    try {
      const result = await apiClient.postJson('/improvements/scheduler/admin/dr-drill', { confirm: true }, 'POST', schedulerHeaders());
      const verification = await apiClient.postJson(`/improvements/scheduler/admin/dr-drills/${encodeURIComponent(result.id)}/verify-restore`, {}, 'POST', schedulerHeaders());
      window.alert(`DR drill ${result.status}: integrity ${result.integrity_check}; restore verification ${verification.verified ? 'passed' : 'failed'}`);
    } catch (err) { setError(err.message); }
    finally { setBusy(''); }
  }

  useEffect(() => { refresh(true); }, [projectName]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ padding: 20, display: 'grid', gap: 16 }}>
      {error && <div style={{ ...box, borderColor: '#f85149', color: '#ff7b72' }}>{error}</div>}

      <div style={{ ...box, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ color: '#8b949e', fontSize: 12 }}>PROJECT HEALTH</div>
          <div style={{ color: scoreTone(health?.health_score || 0), fontSize: 28, fontWeight: 700 }}>
            {health ? health.health_score.toFixed(1) : '—'}
          </div>
          <div style={{ color: '#8b949e', fontSize: 12 }}>
            Policy v{policyRecord?.version || 0} · {policyRecord?.source || 'defaults'} · human apply approval enforced
          </div>
        </div>
        <button style={button} onClick={() => refresh(true)}>Refresh</button>
        <button style={button} onClick={() => startCycle(true)} disabled={!!busy}>Observe</button>
        <button style={primaryButton} onClick={() => startCycle(false)} disabled={!!busy}>Start Improvement</button>
        <button style={button} onClick={approveBaseline} disabled={!!busy}>Approve Current Baseline</button>
      </div>

      <div style={{ ...box, borderColor: readiness?.eligible ? '#238636' : '#d29922' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <div style={{ color: '#8b949e', fontSize: 12 }}>AUTONOMY READINESS · DRY-RUN SCHEDULER ONLY</div>
            <strong style={{ color: readiness?.eligible ? '#3fb950' : '#d29922' }}>{readiness?.verdict || 'checking…'}</strong>
          </div>
          <div style={{ color: '#8b949e', fontSize: 12 }}>{readiness ? `${readiness.summary?.passed || 0}/${readiness.summary?.total || 0} gates passed` : ''}</div>
        </div>
        {!!readiness?.blockers?.length && <div style={{ marginTop: 8, color: '#c9d1d9', fontSize: 12 }}>
          {readiness.blockers.slice(0, 5).map(gate => <div key={gate.name}>• {gate.name}: {gate.message}</div>)}
        </div>}
      </div>

      <div style={{ ...box, borderColor: schedulerState?.status?.kill_switch ? '#f85149' : '#30363d' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div style={{ color: '#8b949e', fontSize: 12 }}>PART 13 STAGING-PROVIDER CONTROL PLANE · SCHEDULED SOURCE APPLY ALWAYS DISABLED</div>
            <strong>{schedulerState?.status?.background_scheduler_enabled ? 'Background polling enabled' : 'Background polling disabled'}</strong>
            <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
              {schedulerState?.schedules?.length || 0} schedules · {schedulerState?.recent_runs?.length || 0} recent runs · kill switch {schedulerState?.status?.kill_switch ? 'ACTIVE' : 'clear'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select value={schedulerEnvironment} onChange={e => setSchedulerEnvironment(e.target.value)} style={button}>
              <option value="dev">Dev</option>
              <option value="staging">Staging</option>
              <option value="prod">Prod</option>
            </select>
            <select value={scheduleMode} onChange={e => setScheduleMode(e.target.value)} style={button}>
              <option value="observe_propose">Observe + propose</option>
              <option value="canary_observe">Canary observe only</option>
            </select>
            <input value={scheduleInterval} onChange={e => setScheduleInterval(e.target.value)} placeholder="Minutes" style={{ ...button, width: 90, cursor: 'text' }} />
            <button style={button} onClick={previewDryRunSchedule} disabled={!!busy}>Simulate</button>
            <button style={button} onClick={createDryRunSchedule} disabled={!!busy}>Add Schedule</button>
            <button style={button} onClick={runSchedulerTick} disabled={!!busy}>Run Due Tick</button>
            <button style={button} onClick={flushSchedulerIntegrations} disabled={!!busy}>Flush Integrations</button>
            <button style={button} onClick={runDisasterRecoveryDrill} disabled={!!busy}>Run DR Drill</button>
            <button style={{ ...button, borderColor: schedulerState?.status?.kill_switch ? '#238636' : '#f85149' }} onClick={toggleKillSwitch} disabled={!!busy}>
              {schedulerState?.status?.kill_switch ? 'Clear Kill Switch' : 'Emergency Stop'}
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <input value={operatorId} onChange={e => setOperatorId(e.target.value)} placeholder="Operator ID" style={{ ...button, cursor: 'text' }} />
          <input type="password" value={operatorToken} onChange={e => setOperatorToken(e.target.value)} placeholder="Operator token" style={{ ...button, cursor: 'text' }} />
          <span style={{ color: '#8b949e', fontSize: 12, alignSelf: 'center' }}>Required when the server operator registry is configured.</span>
        </div>
        <div style={{ color: '#8b949e', fontSize: 12, marginTop: 8 }}>
          Signed webhooks: {schedulerState?.status?.signed_webhook_configured ? 'configured' : 'not configured'} · operator registry: {schedulerState?.status?.operator_registry_configured ? 'configured' : 'not configured'} · fenced leases: {schedulerState?.status?.lease_fencing_enabled ? 'on' : 'off'} · lease backend: {schedulerState?.status?.coordination?.lease_backend || 'sqlite'} · leader election: {schedulerState?.status?.coordination?.leader_election_enabled ? 'on' : 'off'}
          {schedulerMetrics ? ` · open alerts ${schedulerMetrics.open_alerts || 0} · sampled runs ${schedulerMetrics.runs_total_sampled || 0}` : ''}
          {schedulerIntegrations ? ` · alert sink ${schedulerIntegrations.status?.alert_webhook_configured ? 'configured' : 'off'} · OTEL ${schedulerIntegrations.status?.otel_export_configured ? 'configured' : 'off'} · secrets ${schedulerIntegrations.secrets?.provider || 'env'} · status publishing ${schedulerIntegrations.status?.github_status_publishing_configured || schedulerIntegrations.status?.gitlab_status_publishing_configured ? 'configured' : 'off'}` : ''}
        </div>
        {schedulerPreview && <div style={{ marginTop: 8, color: schedulerPreview.would_run ? '#3fb950' : '#d29922', fontSize: 12 }}>
          Simulation: {schedulerPreview.would_run ? 'would run' : 'blocked'}{!schedulerPreview.would_run ? ` · ${(schedulerPreview.decision?.blockers || []).map(g => g.name).join(', ')}` : ''}
        </div>}
        {!!schedulerAlerts.length && <div style={{ marginTop: 8, color: '#d29922', fontSize: 12 }}>
          {schedulerAlerts.slice(0, 3).map(alert => <div key={alert.id}>⚠ {alert.code}: {alert.message}</div>)}
        </div>}
        {!!schedulerState?.schedules?.length && <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
          {schedulerState.schedules.slice(0, 6).map(item => <div key={item.id} style={{ color: '#c9d1d9', fontSize: 12 }}>
            • {item.name} · {item.environment || 'dev'} · {item.mode} · every {item.interval_minutes}m · next {item.next_run_at ? new Date(item.next_run_at).toLocaleString() : 'now'}
          </div>)}
        </div>}
      </div>

      <div style={{ ...box, borderColor: '#8957e5' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div style={{ color: '#8b949e', fontSize: 12 }}>PART 13 STAGING PROVIDERS → VALIDATED RELEASE HANDOFF</div>
            <strong>Staging deployment is supported; production deployment is not</strong>
            <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
              Build {releaseCapabilities?.container_build_mode || 'validate_only'} · staging providers {(stagingCapabilities?.deployment_providers || []).join(', ') || '—'} · SLSA {stagingCapabilities?.slsa_provenance ? 'on' : 'off'} · production deploy {stagingCapabilities?.production_deployment_supported ? 'enabled' : 'DISABLED'}
            </div>
          </div>
          {selectedCycle?.state === 'WAITING_APPROVAL' && selectedCycle?.selected_issue_id && <button style={primaryButton} onClick={createStagingRelease} disabled={!!busy}>Create Staging Release</button>}
        </div>
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          {releases.length === 0 && <span style={{ color: '#8b949e', fontSize: 12 }}>No staging release candidates yet.</span>}
          {releases.slice(0, 8).map(release => <div key={release.id} style={{ border: '1px solid #30363d', borderRadius: 6, padding: 10, display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <strong>{release.status}</strong>
              <div style={{ color: '#8b949e', fontSize: 11 }}>{release.id} · issue {release.issue_id}</div>
              {release.status === 'waiting_vulnerability_evidence' && <div style={{ color: '#d29922', fontSize: 11 }}>Upload Trivy/Grype/generic vulnerability evidence before staging approval.</div>}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {!['staging_ready','rejected'].includes(release.status) && <button style={button} onClick={() => runStagingRelease(release.id)} disabled={!!busy}>Run Pipeline</button>}
              {release.status === 'waiting_staging_approval' && <button style={primaryButton} onClick={() => promoteStagingRelease(release.id)} disabled={!!busy}>Mark Staging Ready</button>}
              {release.status === 'staging_ready' && <button style={button} onClick={() => registerExternalStaging(release.id)} disabled={!!busy}>Register External Staging</button>}
              {release.status === 'staging_validated' && <button style={primaryButton} onClick={() => createProductionReleaseRequest(release.id)} disabled={!!busy}>Create Release Request</button>}
            </div>
          </div>)}
        </div>
      </div>

      <div style={{ ...box, borderColor: '#d29922' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div style={{ color: '#8b949e', fontSize: 12 }}>PART 14/15 GOVERNANCE → INDEPENDENT PRODUCTION DEPLOYER</div>
            <strong>Multi-person governance + exact artifact binding + short-lived deploy authorization</strong>
            <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
              Quorum {governanceCapabilities?.minimum_approvals || 2} · required roles {(governanceCapabilities?.required_roles || []).join(', ') || 'configured'} · production credentials {governanceCapabilities?.production_credentials_stored ? 'present' : 'NOT STORED'} · backend deploy {governanceCapabilities?.production_deployment_supported ? 'enabled' : 'DISABLED'}
            </div>
          </div>
        </div>
        {!!productionRequests.length && <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
          {productionRequests.filter(req => !governanceCases.some(c => c.production_request_id === req.id)).slice(0, 5).map(req => <div key={req.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', border: '1px solid #30363d', borderRadius: 6, padding: 8 }}>
            <span style={{ fontSize: 12 }}>Release request {req.id} · release {req.release_id}</span>
            <button style={button} onClick={() => createGovernanceCase(req.id)} disabled={!!busy}>Open Governance Case</button>
          </div>)}
        </div>}
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          {governanceCases.length === 0 && <span style={{ color: '#8b949e', fontSize: 12 }}>No production-governance cases yet.</span>}
          {governanceCases.slice(0, 8).map(item => <div key={item.id} style={{ border: '1px solid #30363d', borderRadius: 6, padding: 10, display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <div><strong>{item.status}</strong><div style={{ color: '#8b949e', fontSize: 11 }}>{item.id} · release {item.release_id}</div></div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {!item.locked_at && <button style={button} onClick={() => configureGovernanceCase(item.id)} disabled={!!busy}>Ticket + Rollout + Artifact</button>}
              {!item.locked_at && item.status !== 'rejected' && <button style={button} onClick={() => approveGovernanceCase(item.id)} disabled={!!busy}>Approve</button>}
              {!item.locked_at && item.status !== 'rejected' && <button style={primaryButton} onClick={() => lockGovernanceCase(item.id)} disabled={!!busy}>Lock</button>}
              {item.locked_at && item.status !== 'packaged' && <button style={primaryButton} onClick={() => packageGovernanceCase(item.id)} disabled={!!busy}>Create Signed Package</button>}
            </div>
          </div>)}
        </div>
        <div style={{ display: 'grid', gap: 6, marginTop: 12 }}>
          {deploymentPackages.slice(0, 6).map(pkg => <div key={pkg.id} style={{ border: '1px solid #30363d', borderRadius: 6, padding: 8, display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11 }}>Package {pkg.id} · {(pkg.payload?.artifact_binding?.artifact_ref || 'artifact not bound')}</span>
            <button style={button} onClick={() => issueDeploymentAuthorization(pkg.id)} disabled={!!busy}>Issue Deploy Authorization</button>
          </div>)}
        </div>
        <div style={{ marginTop: 12, borderTop: '1px solid #30363d', paddingTop: 10 }}>
          <strong>Production outcome learning</strong>
          <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
            sampled {productionLearning?.outcomes_sampled || 0} · succeeded {productionLearning?.succeeded || 0} · failed {productionLearning?.failed || 0} · rolled back {productionLearning?.rolled_back || 0}
          </div>
          <div style={{ color: '#8b949e', fontSize: 11, marginTop: 4 }}>{productionLearning?.learning_type || 'Persisted operational outcome memory; not model-weight retraining.'}</div>
        </div>
        <div style={{ color: '#8b949e', fontSize: 11, marginTop: 10 }}>The package and authorization are consumed by a separate production-deployer service. This AI backend stores no production deployment credentials and exposes no production executor. Active authorizations: {deploymentAuthorizations.length}.</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, .8fr) minmax(420px, 1.8fr)', gap: 16 }}>
        <div style={box}>
          <h3 style={{ marginTop: 0 }}>Cycles</h3>
          <div style={{ display: 'grid', gap: 8 }}>
            {cycles.length === 0 && <span style={{ color: '#8b949e' }}>No improvement cycles yet.</span>}
            {cycles.map(cycle => (
              <button key={cycle.id} onClick={() => openCycle(cycle.id)} style={{ ...button, textAlign: 'left', background: selectedCycle?.id === cycle.id ? '#1f2937' : '#21262d' }}>
                <div style={{ fontWeight: 600 }}>{cycle.state}</div>
                <div style={{ color: '#8b949e', fontSize: 11 }}>{new Date(cycle.started_at).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </div>

        <div style={box}>
          <h3 style={{ marginTop: 0 }}>Cycle Detail</h3>
          {!selectedCycle && <div style={{ color: '#8b949e' }}>Select a cycle to inspect candidates, experiments, governance, and approval state.</div>}
          {selectedCycle && <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
              <strong>{selectedCycle.state}</strong>
              <span style={{ color: '#8b949e', fontSize: 12 }}>{selectedCycle.id}</span>
              {!selectedCycle.completed_at && selectedCycle.state !== 'APPLYING' && <button style={button} onClick={cancelCycle}>Cancel Cycle</button>}
              {selectedCycle.state === 'WAITING_APPROVAL' && <button style={primaryButton} onClick={applyCycle} disabled={selectedCycle.approval_status && !selectedCycle.approval_status.passed}>Apply Verified Winner</button>}
            </div>

            {selectedCycle.state === 'WAITING_APPROVAL' && selectedCycle.approval_status && !selectedCycle.approval_status.passed && <>
              <h4>Verified Approval Required</h4>
              <div style={{ color: '#8b949e', fontSize: 12, marginBottom: 8 }}>
                {selectedCycle.approval_status.verified_approvals}/{selectedCycle.approval_status.minimum} approvals · required roles: {(selectedCycle.approval_status.required_roles || []).join(', ') || 'configured role'}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                <input value={approverId} onChange={e => setApproverId(e.target.value)} placeholder="Approver ID" style={{ ...button, cursor: 'text' }} />
                <input value={approverRole} onChange={e => setApproverRole(e.target.value)} placeholder="Role" style={{ ...button, cursor: 'text' }} />
                <input type="password" value={approverToken} onChange={e => setApproverToken(e.target.value)} placeholder="Approval token" style={{ ...button, cursor: 'text' }} />
                <button style={button} onClick={approveCycle} disabled={!approverId || !approverRole || !approverToken || !!busy}>Record Verified Approval</button>
              </div>
            </>}

            <h4>Candidates</h4>
            <div style={{ display: 'grid', gap: 8 }}>
              {candidates.map(candidate => (
                <div key={candidate.id} style={{ border: '1px solid #30363d', borderRadius: 6, padding: 10 }}>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between' }}>
                    <strong>{candidate.problem}</strong>
                    <span>{Number(candidate.priority_score || 0).toFixed(3)}</span>
                  </div>
                  <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
                    {candidate.risk} risk{candidate.base_risk && candidate.base_risk !== candidate.risk ? ` (escalated from ${candidate.base_risk})` : ''} · {candidate.status} · repeats {candidate.repeat_count || 0}
                    {candidate.suppressed ? ` · suppressed: ${candidate.suppression_reason}` : ''}
                    {candidate.cooldown_until ? ` · cooldown until ${new Date(candidate.cooldown_until).toLocaleString()}` : ''}
                  </div>
                  {selectedCycle.state === 'WAITING_SELECTION' && !candidate.suppressed && <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <button style={button} onClick={() => chooseCandidate(candidate.id, false)}>Validate</button>
                    <button style={button} onClick={() => chooseCandidate(candidate.id, true)}>Compare 2</button>
                  </div>}
                </div>
              ))}
              {selectableCandidates.length === 0 && candidates.length > 0 && <div style={{ color: '#d29922' }}>All candidates are currently suppressed or blocked by policy.</div>}
            </div>

            {!!selectedCycle.experiments?.length && <>
              <h4>Experiments</h4>
              {selectedCycle.experiments.map(exp => <div key={exp.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #21262d' }}>
                <span>#{exp.experiment_rank} · {exp.status} · quality {exp.quality_score ?? '—'}</span>
                {exp.status !== 'discarded' && exp.candidate_id !== selectedCycle.selected_candidate_id && <button style={button} onClick={() => discardExperiment(exp.id)}>Discard</button>}
              </div>)}
            </>}

            {selectedCycle.result?.governance && <>
              <h4>Governance</h4>
              <pre style={{ whiteSpace: 'pre-wrap', color: '#c9d1d9', fontSize: 12 }}>{JSON.stringify(selectedCycle.result.governance, null, 2)}</pre>
            </>}
          </>}
        </div>
      </div>

      <div style={box}>
        <h3 style={{ marginTop: 0 }}>Project Improvement Policy</h3>
        <p style={{ color: '#8b949e', fontSize: 12 }}>Versioned policy controls candidate risk/categories, protected APIs, architecture invariants, dependency changes, and repeat suppression. Human approval cannot be disabled.</p>
        <textarea value={policyText} onChange={e => setPolicyText(e.target.value)} spellCheck={false}
          style={{ width: '100%', minHeight: 260, boxSizing: 'border-box', background: '#0d1117', color: '#c9d1d9', border: '1px solid #30363d', borderRadius: 6, padding: 12, fontFamily: 'monospace' }} />
        <div style={{ marginTop: 10 }}><button style={primaryButton} onClick={savePolicy} disabled={!!busy}>Save New Policy Version</button></div>
      </div>
    </div>
  );
}
