# Dossier Monitoring & Alerts

This document contains sample alerting rules and dashboard guidance for dossier verification flows.

## Sample Prometheus Alert Rules

Add the following rule to your Prometheus Alerting rules to catch verification mismatches and missing artifacts:

```yaml
groups:
  - name: i4g-dossiers
    rules:
      - alert: DossierVerificationMismatch
        expr: increase(reports_dossiers_verify_mismatch_total[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Dossier verification mismatch detected"
          description: "There were one or more verification mismatches for dossiers in the last 5 minutes."

      - alert: DossierMissingArtifacts
        expr: increase(reports_dossiers_verify_missing_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Dossier verification reported missing artifacts"
          description: "One or more dossiers reported missing artifacts during verification."
```

Note: Metric names depend on your StatsD -> Prometheus bridge. If your setup uses different prefixes or counters,
translate them accordingly.

## Grafana Panel Example

Create a simple single stat or table panel that queries `reports_dossiers_verify_mismatch_total` and colorizes when > 0.

For a detailed trend panel, plot `increase(reports_dossiers_verify_mismatch_total[1h])` grouped by labels such as `plan_id`.

## Remediation Playbook

If either alert fires:
1. Run `i4g-admin process-dossiers --plan-id <plan_id>` to rebuild the manifest and artifacts.
2. Re-run verification: `POST /reports/dossiers/{plan_id}/verify`.
3. If mismatch persists, rebuild the PDF/HTML exports and re-upload; otherwise raise an incident with the artifact path and mismatch details.
