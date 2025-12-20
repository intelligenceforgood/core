#!/usr/bin/env python3
"""
Force reset of migration_user in Azure SQL.
Handles schema ownership and drops/recreates the user to ensure a clean state.
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
        print("👉 Run 'az login' and try again.")
        sys.exit(1)

def reset_password(new_password):
    print(f"Connecting to {SERVER}...")
    conn_str = f"Driver={DRIVER};Server=tcp:{SERVER},1433;Database={DATABASE};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    token_struct = get_aad_token_struct()
    
    try:
        # Use autocommit=True to ensure commands run immediately
        with pyodbc.connect(conn_str, attrs_before={1256: token_struct}, autocommit=True) as conn:
            cursor = conn.cursor()
            
            print("Checking for existing 'migration_user'...")
            cursor.execute("SELECT principal_id FROM sys.database_principals WHERE name = 'migration_user'")
            if cursor.fetchone():
                print("User exists. Cleaning up dependencies...")
                
                # 1. Transfer ownership of any schemas
                cursor.execute("SELECT name FROM sys.schemas WHERE principal_id = USER_ID('migration_user')")
                schemas = cursor.fetchall()
                for s in schemas:
                    print(f"  - Transferring schema '{s[0]}' ownership to dbo")
                    cursor.execute(f"ALTER AUTHORIZATION ON SCHEMA::[{s[0]}] TO dbo")
                
                # 2. Drop the user
                print("  - Dropping existing user")
                cursor.execute("DROP USER migration_user")
            
            # 3. Create fresh contained user
            print("Creating new contained user 'migration_user'...")
            # Note: This creates a user with a password directly in the database (Contained User)
            cursor.execute(f"CREATE USER migration_user WITH PASSWORD = '{new_password}'")
            
            # 4. Grant permissions
            print("Granting db_datareader role...")
            cursor.execute("ALTER ROLE db_datareader ADD MEMBER migration_user")
            
            print("✅ User reset successfully.")
            
    except Exception as ex:
        print(f"❌ Database Error: {ex}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("password")
    args = parser.parse_args()
    reset_password(args.password)
