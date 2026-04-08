view: platform_kpis {
  sql_table_name: `@{dataset}.platform_kpis` ;;

  dimension: period_type {
    type: string
    sql: ${TABLE}.period_type ;;
  }

  dimension: period_start {
    type: date
    sql: ${TABLE}.period_start ;;
  }

  dimension: engagement_id {
    type: string
    sql: ${TABLE}.engagement_id ;;
  }

  measure: total_cases {
    type: sum
    sql: ${TABLE}.total_cases ;;
  }

  measure: proactive_cases {
    type: sum
    sql: ${TABLE}.proactive_cases ;;
  }

  measure: reactive_cases {
    type: sum
    sql: ${TABLE}.reactive_cases ;;
  }

  measure: total_loss {
    type: sum
    sql: ${TABLE}.total_loss ;;
    value_format_name: usd
  }

  measure: new_indicators {
    type: sum
    sql: ${TABLE}.new_indicators ;;
  }

  measure: new_entities {
    type: sum
    sql: ${TABLE}.new_entities ;;
  }

  measure: cases_actioned {
    type: sum
    sql: ${TABLE}.cases_actioned ;;
  }

  measure: action_rate {
    type: number
    description: "Percentage of cases actioned"
    sql: SAFE_DIVIDE(${cases_actioned}, ${total_cases}) * 100 ;;
    value_format: "0.0\%"
  }

  measure: proactive_percentage {
    type: number
    description: "Percentage of cases detected proactively"
    sql: SAFE_DIVIDE(${proactive_cases}, ${total_cases}) * 100 ;;
    value_format: "0.0\%"
  }
}
