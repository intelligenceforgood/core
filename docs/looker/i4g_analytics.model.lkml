connection: "i4g-analytics"
label: "I4G Cross-Engagement Analytics"

include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"

# ---------------------------------------------------------------------------
# Explore: Cross-Engagement KPIs
# ---------------------------------------------------------------------------

explore: platform_kpis {
  label: "Platform KPIs"
  description: "Daily and weekly operational KPIs with engagement and university dimensions."

  join: engagements {
    type: left_outer
    sql_on: ${platform_kpis.engagement_id} = ${engagements.engagement_id} ;;
    relationship: many_to_one
  }

  # Filter out the __global__ sentinel by default so dashboards show
  # per-engagement rows.  Users can explicitly include it.
  sql_always_where: ${platform_kpis.engagement_id} <> '__global__' ;;
}

explore: engagement_analyst_stats {
  label: "Analyst Performance"
  description: "Per-analyst performance metrics within engagements."

  join: engagements {
    type: left_outer
    sql_on: ${engagement_analyst_stats.engagement_id} = ${engagements.engagement_id} ;;
    relationship: many_to_one
  }
}

explore: entity_stats {
  label: "Entity Stats"
  description: "Entity-level risk aggregates (cross-engagement, not scoped)."
}

explore: indicator_stats {
  label: "Indicator Stats"
  description: "Indicator-level frequency and loss aggregates."
}

explore: campaign_stats {
  label: "Campaign Stats"
  description: "Campaign risk scoring and lifecycle metrics."
}
