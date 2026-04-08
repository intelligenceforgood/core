view: engagement_analyst_stats {
  sql_table_name: `@{dataset}.engagement_analyst_stats` ;;

  dimension: engagement_id {
    type: string
    sql: ${TABLE}.engagement_id ;;
  }

  dimension: analyst_email {
    type: string
    sql: ${TABLE}.analyst_email ;;
  }

  measure: total_cases_reviewed {
    type: sum
    sql: ${TABLE}.cases_reviewed ;;
  }

  measure: avg_classification_accuracy {
    type: average
    sql: ${TABLE}.classification_accuracy ;;
    value_format: "0.00%"
  }

  measure: avg_review_time_seconds {
    type: average
    sql: ${TABLE}.avg_review_time_seconds ;;
    value_format: "0.0"
  }

  measure: avg_risk_score_mae {
    type: average
    sql: ${TABLE}.risk_score_mae ;;
    value_format: "0.00"
  }

  measure: total_actions_logged {
    type: sum
    sql: ${TABLE}.actions_logged ;;
  }

  measure: analyst_count {
    type: count_distinct
    sql: ${TABLE}.analyst_email ;;
  }

  dimension_group: last_activity {
    type: time
    timeframes: [raw, date, week]
    sql: ${TABLE}.last_activity_at ;;
  }

  dimension_group: computed {
    type: time
    timeframes: [raw, date]
    sql: ${TABLE}.computed_at ;;
  }
}
