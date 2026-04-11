-- consolidate_entity_types.sql
-- Merge account_number, routing_number → bank_account;
-- bank, retailer → organization; software → scam_indicator.
-- Also fix bare "account" and "transaction" types.
--
-- Compatible with both SQLite and PostgreSQL.
--
-- Local (SQLite):
--   sqlite3 data/i4g_store.db "PRAGMA foreign_keys=ON;" ".read scripts/consolidate_entity_types.sql"
--
-- Dev (PostgreSQL):
--   psql "$DATABASE_URL" -f scripts/consolidate_entity_types.sql
-- ---------------------------------------------------------------

-- ================================================================
-- 1.  entities table — dedup before rename
--
--     Unique constraint: (case_id, entity_type, canonical_value).
--     Delete rows that would collide with existing bank_account rows.
-- ================================================================

-- account_number → bank_account (delete if bank_account already has the same value)
DELETE FROM entities WHERE entity_type = 'account_number'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'bank_account');

-- routing_number → bank_account
DELETE FROM entities WHERE entity_type = 'routing_number'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'bank_account');

-- bare "account" → bank_account
DELETE FROM entities WHERE entity_type = 'account'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'bank_account');

-- bank → organization
DELETE FROM entities WHERE entity_type = 'bank'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'organization');

-- retailer → organization
DELETE FROM entities WHERE entity_type = 'retailer'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'organization');

-- ================================================================
-- 2.  Rename entity types
-- ================================================================

UPDATE entities SET entity_type = 'bank_account'   WHERE entity_type = 'account_number';
UPDATE entities SET entity_type = 'bank_account'   WHERE entity_type = 'routing_number';
UPDATE entities SET entity_type = 'bank_account'   WHERE entity_type = 'account';
UPDATE entities SET entity_type = 'transaction_id' WHERE entity_type = 'transaction';
UPDATE entities SET entity_type = 'organization'   WHERE entity_type = 'bank';
UPDATE entities SET entity_type = 'organization'   WHERE entity_type = 'retailer';
UPDATE entities SET entity_type = 'scam_indicator' WHERE entity_type = 'software';

-- ================================================================
-- 3.  indicators table — same consolidation
-- ================================================================

DELETE FROM indicators WHERE category = 'account_number'
    AND EXISTS (SELECT 1
    FROM indicators i2
    WHERE i2.dataset = indicators.dataset
        AND i2.number = indicators.number
        AND i2.category = 'bank_account');

DELETE FROM indicators WHERE category = 'routing_number'
    AND EXISTS (SELECT 1
    FROM indicators i2
    WHERE i2.dataset = indicators.dataset
        AND i2.number = indicators.number
        AND i2.category = 'bank_account');

UPDATE indicators SET category = 'bank_account'   WHERE category = 'account_number';
UPDATE indicators SET category = 'bank_account'   WHERE category = 'routing_number';
UPDATE indicators SET category = 'bank_account'   WHERE category = 'account';
UPDATE indicators SET category = 'transaction_id' WHERE category = 'transaction';
UPDATE indicators SET category = 'organization'   WHERE category = 'bank';
UPDATE indicators SET category = 'organization'   WHERE category = 'retailer';

-- ================================================================
-- 4.  Clear aggregated stats — will be recomputed
-- ================================================================

DELETE FROM entity_stats;

-- ================================================================
-- 5.  Verification
-- ================================================================
-- SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY entity_type;
-- Expected: no account_number, routing_number, bank, retailer, software, account, transaction
