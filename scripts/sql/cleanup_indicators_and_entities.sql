-- cleanup_indicators_and_entities.sql
-- Idempotent cleanup for Sprint 1 entity extraction overhaul:
--   1. Delete indicator rows for non-threat entity types
--   2. Fix entity_type for entities that were mistyped due to old NER mapping
--   3. Fix contact_channels → proper split types
--
-- Compatible with both SQLite and PostgreSQL.
--
-- Local (SQLite):
--   sqlite3 data/i4g_store.db ".read scripts/cleanup_indicators_and_entities.sql"
--
-- Dev (PostgreSQL):
--   psql "$DATABASE_URL" -f scripts/cleanup_indicators_and_entities.sql
-- ---------------------------------------------------------------

-- ================================================================
-- 1. Remove indicator rows for non-threat entity types
--
--    Person, organization, location, scam_indicator, crypto_token
--    should never have been indicators.
-- ================================================================

DELETE FROM indicators
WHERE category IN (
    'person', 'people',
    'organization', 'organizations',
    'location', 'locations',
    'scam_indicator', 'scam_indicators',
    'crypto_token', 'crypto_assets',
    'software'
);

-- ================================================================
-- 2. Fix BANK_ACCOUNT entities that were mistyped as wallet_address
--
--    The old ML NER mapping sent BANK_ACCOUNT → wallet_addresses
--    which normalized to wallet_address. We can't distinguish these
--    from real wallet_addresses in the DB, so just log the issue.
--    Future extractions will map correctly.
-- ================================================================

-- (No automated fix for (2) — requires manual review or re-extraction.)

-- ================================================================
-- 3. Fix contact_channels → split into proper canonical types
--
--    contact_channels was a catch-all for URLs, phones, and emails.
--    Re-classify based on value patterns.
-- ================================================================

-- URLs
UPDATE entities SET entity_type = 'url'
WHERE entity_type = 'contact_handle'
    AND (canonical_value LIKE 'http://%'
    OR canonical_value LIKE 'https://%'
    OR canonical_value LIKE 't.me/%'
    OR canonical_value LIKE 'wa.me/%');

-- Email addresses
UPDATE entities SET entity_type = 'email_address'
WHERE entity_type = 'contact_handle'
    AND canonical_value LIKE '%@%.%';

-- Phone numbers (digits, +, dashes, spaces, parens)
UPDATE entities SET entity_type = 'phone_number'
WHERE entity_type = 'contact_handle'
    AND canonical_value
GLOB '+[0-9]*'
  AND length
(canonical_value) >= 7;

-- Fix indicators of the same patterns
UPDATE indicators SET category = 'url', type = 'url'
WHERE category = 'contact_handle'
    AND (number LIKE 'http://%'
    OR number LIKE 'https://%'
    OR number LIKE 't.me/%'
    OR number LIKE 'wa.me/%');

UPDATE indicators SET category = 'email_address', type = 'email_address'
WHERE category = 'contact_handle'
    AND number LIKE '%@%.%';

UPDATE indicators SET category = 'phone_number', type = 'phone_number'
WHERE category = 'contact_handle'
    AND number
GLOB '+[0-9]*'
  AND length
(number) >= 7;

-- ================================================================
-- 4. Normalize remaining legacy plural types in entities table
-- ================================================================

-- Deduplicate before rename: remove rows that would collide
DELETE FROM entities WHERE entity_type = 'contact_channels'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'contact_handle');

UPDATE entities SET entity_type = 'contact_handle' WHERE entity_type = 'contact_channels';

DELETE FROM entities WHERE entity_type = 'email_address'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'email_address'
        AND e2.entity_id != entities.entity_id);

DELETE FROM entities WHERE entity_type = 'bank_account'
    AND EXISTS (SELECT 1
    FROM entities e2
    WHERE e2.case_id = entities.case_id
        AND e2.canonical_value = entities.canonical_value
        AND e2.entity_type = 'bank_account'
        AND e2.entity_id != entities.entity_id);

-- ================================================================
-- 5. Verification (run interactively after applying)
-- ================================================================
-- SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY entity_type;
-- SELECT category, COUNT(*) FROM indicators GROUP BY category ORDER BY category;
