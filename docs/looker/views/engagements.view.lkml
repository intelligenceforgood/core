view: engagements {
  sql_table_name: `@{dataset}.engagements` ;;

  dimension: engagement_id {
    primary_key: yes
    type: string
    sql: ${TABLE}.engagement_id ;;
  }

  dimension: name {
    type: string
    sql: ${TABLE}.name ;;
  }

  dimension: description {
    type: string
    sql: ${TABLE}.description ;;
  }

  dimension: status {
    type: string
    sql: ${TABLE}.status ;;
  }

  dimension_group: starts_at {
    type: time
    timeframes: [raw, date, week, month, quarter, year]
    sql: ${TABLE}.starts_at ;;
  }

  dimension_group: ends_at {
    type: time
    timeframes: [raw, date, week, month, quarter, year]
    sql: ${TABLE}.ends_at ;;
  }

  dimension: created_by {
    type: string
    sql: ${TABLE}.created_by ;;
  }

  dimension: university {
    type: string
    description: "Extracted from metadata JSON"
    sql: JSON_EXTRACT_SCALAR(${TABLE}.metadata, '$.university') ;;
  }

  dimension_group: created_at {
    type: time
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.created_at ;;
  }

  measure: count {
    type: count
    drill_fields: [engagement_id, name, status, university]
  }
}
