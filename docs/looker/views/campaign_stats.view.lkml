view: campaign_stats {
  sql_table_name: `@{dataset}.campaign_stats` ;;

  dimension: campaign_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.campaign_id ;;
  }

  measure: total_case_count {
    type: sum
    sql: ${TABLE}.case_count ;;
  }

  measure: total_indicator_count {
    type: sum
    sql: ${TABLE}.indicator_count ;;
  }

  measure: total_loss {
    type: sum
    sql: ${TABLE}.loss_sum ;;
    value_format_name: usd
  }

  measure: total_victim_count {
    type: sum
    sql: ${TABLE}.victim_count ;;
  }

  measure: avg_risk_score {
    type: average
    sql: ${TABLE}.risk_score ;;
    value_format: "0.0"
  }

  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }

  dimension_group: first_case {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.first_case_at ;;
  }

  dimension_group: last_case {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.last_case_at ;;
  }

  measure: campaign_count {
    type: count
    drill_fields: [campaign_id, total_case_count, total_loss, avg_risk_score]
  }
}
