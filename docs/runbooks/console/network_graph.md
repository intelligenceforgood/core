# Network Graph Operations Runbook

## Graph Performance Monitoring

The graph endpoint can be resource-intensive for densely connected entities.
Monitor these signals:

- **Response time**: `/intelligence/graph` P95 should stay under 3s for
  hops ≤ 2. Alert if P95 exceeds 5s.
- **Layout computation**: For graphs >500 nodes, server-side spring layout
  runs via NetworkX. Check Cloud Run CPU utilization during layout computation.
- **Memory usage**: Large graphs (>1000 nodes) may increase memory consumption.
  Monitor Cloud Run instance memory against the configured limit.

## Layout Fallback Triggers

When a graph exceeds 500 nodes, the API pre-computes positions using
`NetworkX.spring_layout`. This prevents the frontend from freezing during
force simulation on the client.

If layout computation times out:

1. Check if the entity has an unusually high degree (many connections).
2. Reduce the hop count in the request.
3. Apply entity-type or risk-threshold filters to reduce graph size.

## D3.js Rendering Issues

The frontend uses a canvas-based renderer. Common issues:

- **Blank canvas**: Ensure the browser supports HTML5 Canvas. Check for
  JavaScript errors in the browser console.
- **Performance degradation**: Graphs >2000 nodes may cause frame drops.
  The hop slider is limited to 3 to mitigate this.
- **Export failures**: PNG/SVG export requires the graph to be fully rendered.
  Wait for the loading indicator to clear before exporting.

## Troubleshooting

| Symptom               | Check                                                      |
| --------------------- | ---------------------------------------------------------- |
| 500 on graph endpoint | Check Cloud Run logs for `GraphService` exceptions         |
| Empty graph returned  | Verify seed entity exists in `entity_stats` table          |
| Slow layout           | Check node count; consider reducing hops or adding filters |
| Export timeout        | Reduce graph size; check Cloud Run CPU allocation          |
