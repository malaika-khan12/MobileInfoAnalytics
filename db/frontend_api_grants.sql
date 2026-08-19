-- MobileInfoAnalytics frontend/control-plane grants
-- Run AFTER db/functions_supabase.sql (or the finalized functions SQL).
-- The finalized analytics views are created by the functions SQL after the
-- broad grants in the schema SQL, so they need explicit privileges once they exist.
-- This changes permissions only; it creates/alters no schema objects or data.

GRANT USAGE ON SCHEMA analytics TO service_role;
GRANT SELECT ON
    analytics.v_canonical_products,
    analytics.v_market_listings_full,
    analytics.v_price_comparison,
    analytics.v_spec_discrepancies,
    analytics.v_site_summary
TO service_role;

-- Keep future analytics views readable by the server role when created by
-- the same database owner that executes this statement.
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
    GRANT SELECT ON TABLES TO service_role;
