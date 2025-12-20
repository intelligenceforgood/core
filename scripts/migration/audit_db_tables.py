#!/usr/bin/env python3
"""
Audit script to list all tables in the Azure SQL database and their row counts.
Use this to verify if we are missing any tables in the migration.
"""
import argparse
import struct
import pyodbc
import sys
from azure.identity import DefaultAzureCredential

SERVER = "intelforgood.database.windows.net"
DATABASE = "intelforgood"
DRIVER = "{ODBC Driver 18 for SQL Server}"

def get_aad_token_struct():
    try:
        cred = DefaultAzureCredential()
        token = cred.get_token("https://database.windows.net/.default")
        token_bytes = token.token.encode("utf-16-le")
        return struct.pack("=I", len(token_bytes)) + token_bytes
    except Exception as e:
        print(f"❌ Failed to get Azure AD token: {e}")
        sys.exit(1)

def audit_tables():
    print(f"Connecting to {SERVER}...")
    conn_str = f"Driver={DRIVER};Server=tcp:{SERVER},1433;Database={DATABASE};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"
    token_struct = get_aad_token_struct()
    
    try:
        with pyodbc.connect(conn_str, attrs_before={1256: token_struct}) as conn:
            cursor = conn.cursor()
            
            print("\n--- Database Table Audit ---")
            print(f"{'Schema':<15} {'Table':<40} {'Row Count':>15}")
            print("-" * 75)
            
            # Query to get all tables and their row counts
            query = """
            SELECT 
                s.name AS SchemaName,
                t.name AS TableName,
                SUM(p.rows) AS RowCounts
            FROM 
                sys.tables t
            INNER JOIN      
                sys.indexes i ON t.object_id = i.object_id
            INNER JOIN 
                sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
            INNER JOIN 
                sys.schemas s ON t.schema_id = s.schema_id
            WHERE 
                t.is_ms_shipped = 0
                AND i.object_id > 255 
                AND i.index_id <= 1
            GROUP BY 
                t.name, s.name
            ORDER BY 
                RowCounts DESC;
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            total_rows = 0
            for row in rows:
                schema, table, count = row
                print(f"{schema:<15} {table:<40} {count:>15,}")
                total_rows += count
                
            print("-" * 75)
            print(f"{'TOTAL':<56} {total_rows:>15,}")
            
    except Exception as ex:
        print(f"❌ Database Error: {ex}")
        sys.exit(1)

if __name__ == "__main__":
    audit_tables()
