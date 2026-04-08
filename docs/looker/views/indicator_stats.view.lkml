view: indicator_stats {
  sql_table_name: `@{dataset}.indicator_stats` ;;

  dimension: indicator_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.indicator_id ;;
  }

  dimension: category {
    type: string
    sql: ${TABLE}.category ;;
  }

  dimension: type {
    type: string
    sql: ${TABLE}.type ;;
  }

  dimension: number {
    type: string
    sql: ${TABLE}.number ;;
  }

  measure: total_case_count {
    type: sum
    sql: ${TABLE}.case_count ;;
  }

  measure: total_loss {
    type: sum
    sql: ${TABLE}.loss_sum ;;
    value_format_name: usd
  }

  dimension: ecx_status {
    type: string
    sql: ${TABLE}.ecx_status ;;
  }

  dimension_group: first_seen {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.first_seen_at ;;
  }

  measure: indicator_count {
    type: count
    drill_fields: [indicator_id, category, type, total_case_count, total_loss]
  }
}
