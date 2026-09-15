# Part 15 Production Deployer Runbook

## 1. Trust boundary

Run `production-deployer` independently from the AI backend. Do not mount `/workspace/projects` or the backend source into the deployer. Give production credentials only to the deployer through workload identity, a dedicated service account, or read-only secret files. The AI backend receives no production credential.

## 2. Keys

Use two distinct key purposes:

1. **Package/authorization verification:** configure the deployer with `PRODUCTION_DEPLOYER_PACKAGE_SIGNING_KEY` matching the governance signing material.
2. **Production receipt signing:** configure `PRODUCTION_DEPLOYER_RECEIPT_SIGNING_KEY`; configure the same value on the AI backend as `IMPROVEMENT_PRODUCTION_OUTCOME_SIGNING_KEY`.

Rotate these using your external secrets system. Never submit them through an API request.

## 3. Operators

Configure a separate deployer operator registry:

```json
{
  "release-operator-1": {"role": "deployer", "token": "..."}
}
```

Use headers `X-Production-Operator-ID` and `X-Production-Operator-Token` for mutation endpoints.

## 4. Handoff procedure

1. Complete Part 14 governance.
2. Bind the exact immutable production artifact reference and SHA-256 before approvals/lock.
3. Generate the signed deployment package.
4. Immediately before deployment, issue a short-lived deployment authorization.
5. Transfer package + authorization to the independent deployer.
6. Call `/packages/verify` first.
7. Create deployment with `confirm=true`.
8. Execute or advance rollout stages only with authenticated production operator identity.
9. Observe SLOs at each stage.
10. Retrieve the signed terminal receipt. The configured callback can submit it to the AI backend outcome endpoint.

## 5. Execution modes

`PRODUCTION_DEPLOYER_EXECUTION_ENABLED=false` is the default. In this mode, the service can verify handoffs and orchestrate externally executed canary/blue-green evidence without direct production commands. Enable direct rolling Kubernetes/ECS execution only after production workload identity and target conventions are reviewed.

## 6. SLO halt / rollback

Default gates:

- availability >= 99%
- error rate <= 1%
- P95 latency <= 2500 ms
- health = healthy/ok/pass/passed

Failed evidence halts the rollout. With auto rollback enabled, a direct rolling deployment restores the previously captured image/task definition. External staged rollouts produce a rollback request rather than pretending a provider-specific rollback was executed.

## 7. Production learning

The AI backend verifies the receipt signature and stores terminal outcomes. It links them to the candidate strategy that created the release. A strategy with repeated production failure or rollback is subsequently de-prioritized and risk-escalated. This is persistent operational feedback, not training on source code or production data.

Inspect:

```text
GET /improvements/production-outcomes?project_name=<project>
GET /improvements/production-outcomes/learning?project_name=<project>
```

## 8. Incident procedure

If rollout health degrades: stop stage advancement; submit the latest SLO observation; verify the deployment enters halted/rolled-back state; preserve the signed receipt; confirm the receipt reached the AI backend; and do not issue a new authorization until the failure has been diagnosed and a new governed package exists.
