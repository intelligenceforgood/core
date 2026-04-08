view: entity_stats {
  sql_table_name: `@{dataset}.entity_stats` ;;

  dimension: entity_type {
    type: string
    sql: ${TABLE}.entity_type ;;
  }

  dimension: canonical_value {
    type: string
    sql: ${TABLE}.canonical_value ;;
  }

  measure: total_case_count {
    type: sum
    sql: ${TABLE}.case_count ;;
  }

  measure: total_victim_count {
    type: sum
    sql: ${TABLE}.victim_count ;;
  }

  measure: total_loss {
    type: sum
    sql: ${TABLE}.loss_sum ;;
    value_format_name: usd
  }

  measure: avg_risk_score {
    type: average
    sql: ${TABLE}.avg_risk_score ;;
    value_format: "0.0"
  }

  measure: max_risk_score {
    type: max
    sql: ${TABLE}.max_risk_score ;;
    value_format: "0.0"
  }

  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }

  dimension: ecx_submitted {
    type: yesno
    sql: ${TABLE}.ecx_submitted ;;
  }

  dimension: ecx_hit {
    type: yesno
    sql: ${TABLE}.ecx_hit ;;
  }

  dimension_group: first_seen {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.first_seen_at ;;
  }

  dimension_group: last_seen {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.last_seen_at ;;
  }

  measure: entity_count {
    type: count
    drill_fields: [entity_type, canonical_value, total_case_count, total_loss]
  }
}
