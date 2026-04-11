-- fix_entity_types.sql
-- Normalise entity_type values to singular, consistent names.
-- Compatible with both SQLite and PostgreSQL.
--
-- Local (SQLite):
--   sqlite3 data/i4g_store.db "PRAGMA foreign_keys=ON;" ".read scripts/fix_entity_types.sql"
--
-- Dev (PostgreSQL):
--   psql "$DATABASE_URL" -f scripts/fix_entity_types.sql
-- ---------------------------------------------------------------

-- ================================================================
-- 1.  entities  table  (raw extraction rows)
--
--     Unique constraint: (case_id, entity_type, canonical_value).
--     Delete rows that would collide with an existing row under
--     the new canonical type before renaming.
-- ================================================================

-- Remove duplicates that would conflict after rename
DELETE FROM entities WHERE entity_type = 'people'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'person');

DELETE FROM entities WHERE entity_type = 'organizations'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'organization');

DELETE FROM entities WHERE entity_type = 'wallet_addresses'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'crypto_wallet');

DELETE FROM entities WHERE entity_type = 'crypto_assets'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'crypto_wallet');

-- Plural to singular
UPDATE entities SET entity_type = 'person'         WHERE entity_type = 'people';
UPDATE entities SET entity_type = 'organization'   WHERE entity_type = 'organizations';
UPDATE entities SET entity_type = 'phone_number'   WHERE entity_type = 'phone_numbers';
UPDATE entities SET entity_type = 'account_number' WHERE entity_type = 'account_numbers';
UPDATE entities SET entity_type = 'routing_number' WHERE entity_type = 'routing_numbers';
UPDATE entities SET entity_type = 'transaction_id' WHERE entity_type = 'transaction_ids';
UPDATE entities SET entity_type = 'ticket_id'      WHERE entity_type = 'ticket_ids';
UPDATE entities SET entity_type = 'location'       WHERE entity_type = 'locations';
UPDATE entities SET entity_type = 'bank'           WHERE entity_type = 'banks';
UPDATE entities SET entity_type = 'agency'         WHERE entity_type = 'agencies';
UPDATE entities SET entity_type = 'retailer'       WHERE entity_type = 'retailers';
UPDATE entities SET entity_type = 'scam_indicator' WHERE entity_type = 'scam_indicators';

-- Synonym merges
UPDATE entities SET entity_type = 'crypto_wallet'  WHERE entity_type = 'wallet_addresses';
UPDATE entities SET entity_type = 'crypto_wallet'  WHERE entity_type = 'crypto_assets';

-- Ambiguous to descriptive
UPDATE entities SET entity_type = 'social_handle'  WHERE entity_type = 'handles';
UPDATE entities SET entity_type = 'crypto_token'   WHERE entity_type = 'tokens';


-- ================================================================
-- 2.  entity_stats  table  (aggregated stats)
--
--     entity_type is part of the composite PK (entity_type, canonical_value).
--     After renaming, rows may collide on the same PK.  Delete all
--     and let the analytics aggregation job re-compute from the
--     now-clean entities table.
-- ================================================================

DELETE FROM entity_stats;


-- ================================================================
-- 3.  Verification  (run interactively after applying)
-- ================================================================
-- SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY entity_type;
