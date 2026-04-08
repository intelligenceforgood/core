- dashboard: cross_engagement_analytics
  title: "Cross-Engagement Analytics"
  layout: newspaper
  preferred_viewer: dashboards-next
  description: |
    Semester-over-semester trend analysis and university partnership comparison.
    Data refreshed daily from Cloud SQL via the bq-export job.

  filters:
  - name: engagement_status
    title: "Engagement Status"
    type: field_filter
    explore: platform_kpis
    field: engagements.status
    default_value: "active,completed"

  - name: date_range
    title: "Date Range"
    type: date_filter
    default_value: "12 months"

  - name: university
    title: "University"
    type: field_filter
    explore: platform_kpis
    field: engagements.university
    default_value: ""

  elements:

  # ---- Row 1: Summary KPI cards ----

  - title: "Total Engagements"
    name: total_engagements
    model: i4g_analytics
    explore: platform_kpis
    type: single_value
    fields: [engagements.count]
    filters:
      engagements.status: "active,completed"
    row: 0
    col: 0
    width: 4
    height: 3

  - title: "Total Cases (All Engagements)"
    name: total_cases
    model: i4g_analytics
    explore: platform_kpis
    type: single_value
    fields: [platform_kpis.total_cases]
    row: 0
    col: 4
    width: 4
    height: 3

  - title: "Total Financial Loss"
    name: total_loss
    model: i4g_analytics
    explore: platform_kpis
    type: single_value
    fields: [platform_kpis.total_loss]
    row: 0
    col: 8
    width: 4
    height: 3

  - title: "Active Analysts"
    name: active_analysts
    model: i4g_analytics
    explore: engagement_analyst_stats
    type: single_value
    fields: [engagement_analyst_stats.analyst_count]
    row: 0
    col: 12
    width: 4
    height: 3

  # ---- Row 2: Semester-over-semester trends ----

  - title: "Cases by Engagement Over Time"
    name: cases_trend
    model: i4g_analytics
    explore: platform_kpis
    type: looker_line
    fields: [platform_kpis.period_start, engagements.name, platform_kpis.total_cases]
    pivots: [engagements.name]
    sorts: [platform_kpis.period_start]
    row: 3
    col: 0
    width: 12
    height: 8

  - title: "Loss by Engagement Over Time"
    name: loss_trend
    model: i4g_analytics
    explore: platform_kpis
    type: looker_line
    fields: [platform_kpis.period_start, engagements.name, platform_kpis.total_loss]
    pivots: [engagements.name]
    sorts: [platform_kpis.period_start]
    row: 3
    col: 12
    width: 12
    height: 8

  # ---- Row 3: University comparison ----

  - title: "Cases by University"
    name: cases_by_university
    model: i4g_analytics
    explore: platform_kpis
    type: looker_bar
    fields: [engagements.university, platform_kpis.total_cases]
    sorts: [platform_kpis.total_cases desc]
    row: 11
    col: 0
    width: 8
    height: 8

  - title: "Loss by University"
    name: loss_by_university
    model: i4g_analytics
    explore: platform_kpis
    type: looker_bar
    fields: [engagements.university, platform_kpis.total_loss]
    sorts: [platform_kpis.total_loss desc]
    row: 11
    col: 8
    width: 8
    height: 8

  - title: "Action Rate by University"
    name: action_rate_by_university
    model: i4g_analytics
    explore: platform_kpis
    type: looker_bar
    fields: [engagements.university, platform_kpis.action_rate]
    sorts: [platform_kpis.action_rate desc]
    row: 11
    col: 16
    width: 8
    height: 8

  # ---- Row 4: Analyst performance cross-engagement ----

  - title: "Avg Classification Accuracy by Engagement"
    name: accuracy_by_engagement
    model: i4g_analytics
    explore: engagement_analyst_stats
    type: looker_bar
    fields: [engagements.name, engagement_analyst_stats.avg_classification_accuracy]
    sorts: [engagement_analyst_stats.avg_classification_accuracy desc]
    row: 19
    col: 0
    width: 12
    height: 8

  - title: "Analyst Count by Engagement"
    name: analysts_by_engagement
    model: i4g_analytics
    explore: engagement_analyst_stats
    type: looker_bar
    fields: [engagements.name, engagement_analyst_stats.analyst_count]
    sorts: [engagement_analyst_stats.analyst_count desc]
    row: 19
    col: 12
    width: 12
    height: 8
