-- =============================================================================
-- MobileInfoAnalytics - Supabase PostgreSQL Functions, Procedures & Views (v3)
-- Target: PostgreSQL 15+ / Supabase
-- Architecture: Hardened for Row Level Security (RLS) with SECURITY DEFINER
-- =============================================================================

-- Ensure all required schemas exist before defining functions & views
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS specs;
CREATE SCHEMA IF NOT EXISTS listings;
CREATE SCHEMA IF NOT EXISTS metadata;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS etl;

-- =============================================================================
-- 1. UTILITY & SLUG FUNCTIONS
-- =============================================================================

-- Function: catalog.slugify (Converts arbitrary text to URL/Key-safe slug)
CREATE OR REPLACE FUNCTION catalog.slugify(p_text TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    v_slug TEXT;
BEGIN
    IF p_text IS NULL OR TRIM(p_text) = '' THEN
        RETURN 'unknown';
    END IF;

    v_slug := LOWER(TRIM(p_text));
    -- Remove non-alphanumeric characters (keep spaces and hyphens)
    v_slug := REGEXP_REPLACE(v_slug, '[^a-z0-9\s-]', '', 'g');
    -- Replace spaces and underscores with a single hyphen
    v_slug := REGEXP_REPLACE(v_slug, '[\s_]+', '-', 'g');
    -- Remove leading or trailing hyphens
    v_slug := TRIM(BOTH '-' FROM v_slug);

    IF v_slug = '' THEN
        RETURN 'unknown';
    END IF;

    RETURN v_slug;
END;
$$;

COMMENT ON FUNCTION catalog.slugify IS 'Normalizes product and brand names into unique standard slugs.';


-- Function: catalog.get_or_create_company (SECURITY DEFINER to operate under RLS)
CREATE OR REPLACE FUNCTION catalog.get_or_create_company(p_company_name TEXT)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = catalog, public
AS $$
DECLARE
    v_clean_name TEXT;
    v_slug TEXT;
    v_company_id BIGINT;
BEGIN
    v_clean_name := COALESCE(NULLIF(TRIM(p_company_name), ''), 'Unknown');
    v_slug := catalog.slugify(v_clean_name);

    SELECT company_id INTO v_company_id
    FROM catalog.companies
    WHERE company_slug = v_slug;

    IF v_company_id IS NULL THEN
        INSERT INTO catalog.companies (company_name, company_slug)
        VALUES (v_clean_name, v_slug)
        ON CONFLICT (company_slug) DO UPDATE
            SET company_name = EXCLUDED.company_name
        RETURNING company_id INTO v_company_id;
    END IF;

    RETURN v_company_id;
END;
$$;


-- Function: catalog.resolve_or_create_product (SECURITY DEFINER to operate under RLS)
CREATE OR REPLACE FUNCTION catalog.resolve_or_create_product(
    p_company_name TEXT,
    p_mobile_name TEXT,
    p_source_domain TEXT,
    p_source_title TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = catalog, public
AS $$
DECLARE
    v_company_id BIGINT;
    v_company_name TEXT;
    v_mobile_name TEXT;
    v_product_slug TEXT;
    v_alias_slug TEXT;
    v_product_id BIGINT;
BEGIN
    v_company_name := COALESCE(NULLIF(TRIM(p_company_name), ''), 'Unknown');
    v_mobile_name := COALESCE(NULLIF(TRIM(p_mobile_name), ''), 'Unknown');

    v_company_id := catalog.get_or_create_company(v_company_name);

    -- Standard full slug e.g. "xiaomi-redmi-note-14-4g"
    v_product_slug := catalog.slugify(v_company_name || ' ' || v_mobile_name);

    -- 1. Check direct product slug match
    SELECT product_id INTO v_product_id
    FROM catalog.products
    WHERE product_slug = v_product_slug;

    IF v_product_id IS NOT NULL THEN
        -- Ensure alias is registered if this source has an extra title
        IF p_source_title IS NOT NULL AND TRIM(p_source_title) <> '' THEN
            v_alias_slug := catalog.slugify(p_source_title);
            INSERT INTO catalog.product_aliases (product_id, alias_name, alias_slug, source_domain)
            VALUES (v_product_id, TRIM(p_source_title), v_alias_slug, p_source_domain)
            ON CONFLICT (alias_slug) DO NOTHING;
        END IF;
        RETURN v_product_id;
    END IF;

    -- 2. Check alias slug match
    v_alias_slug := catalog.slugify(COALESCE(NULLIF(TRIM(p_source_title), ''), v_mobile_name));
    SELECT product_id INTO v_product_id
    FROM catalog.product_aliases
    WHERE alias_slug = v_alias_slug OR alias_slug = v_product_slug;

    IF v_product_id IS NOT NULL THEN
        RETURN v_product_id;
    END IF;

    -- 3. No existing match: Create new central product node
    INSERT INTO catalog.products (
        company_id, mobile_name, product_slug, created_by_source
    )
    VALUES (
        v_company_id, v_mobile_name, v_product_slug, COALESCE(p_source_domain, 'unknown')
    )
    RETURNING product_id INTO v_product_id;

    -- Register default aliases for future cross-site matches
    INSERT INTO catalog.product_aliases (product_id, alias_name, alias_slug, source_domain)
    VALUES
        (v_product_id, v_company_name || ' ' || v_mobile_name, v_product_slug, p_source_domain)
    ON CONFLICT (alias_slug) DO NOTHING;

    IF p_source_title IS NOT NULL AND TRIM(p_source_title) <> '' AND v_alias_slug <> v_product_slug THEN
        INSERT INTO catalog.product_aliases (product_id, alias_name, alias_slug, source_domain)
        VALUES (v_product_id, TRIM(p_source_title), v_alias_slug, p_source_domain)
        ON CONFLICT (alias_slug) DO NOTHING;
    END IF;

    RETURN v_product_id;
END;
$$;

COMMENT ON FUNCTION catalog.resolve_or_create_product IS
'Resolves a mobile phone to a central product_id using slug/alias matching or creates a new product if first seen.';


-- =============================================================================
-- 2. INGESTION FUNCTION FOR template_v2 JSON (RLS Hardened)
-- =============================================================================

CREATE OR REPLACE FUNCTION etl.ingest_template_v2_json(
    p_json JSONB,
    p_source_domain TEXT,
    p_source_file TEXT DEFAULT NULL,
    p_scrape_run_id BIGINT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = catalog, specs, listings, metadata, staging, analytics, public
AS $$
DECLARE
    v_product_id BIGINT;
    v_listing_id BIGINT;
    v_instance_num INT;
    v_company_name TEXT;
    v_mobile_name TEXT;
    v_source_url TEXT;
    v_is_canonical BOOLEAN;
    v_has_canonical_specs BOOLEAN;
    
    -- Price parsing variables
    v_price_elem JSONB;
    v_price_idx INT := 0;
    v_price_val NUMERIC;
    v_currency VARCHAR(3);
    
    -- Quality calculation variables
    v_fields_populated INT := 0;
    v_fields_total INT := 28;
    v_completeness NUMERIC(5,2);
BEGIN
    IF p_json IS NULL OR p_json = '{}'::jsonb THEN
        RAISE EXCEPTION 'Payload is empty or null';
    END IF;

    v_company_name := COALESCE(p_json->>'CompanyName', 'Unknown');
    v_mobile_name := COALESCE(p_json->>'MobileName', 'Unknown');
    v_source_url := COALESCE(p_json->>'URL', 'https://' || p_source_domain || '/unknown-' || uuid_generate_v4()::text);

    -- 1. Resolve or create central product ID
    v_product_id := catalog.resolve_or_create_product(
        v_company_name,
        v_mobile_name,
        p_source_domain,
        v_mobile_name
    );

    -- Determine instance number for this product and source
    SELECT COALESCE(MAX(instance_number), 0) + 1 INTO v_instance_num
    FROM listings.market_listings
    WHERE product_id = v_product_id AND source_domain = p_source_domain
      AND source_url <> v_source_url;

    -- 2. Insert or update market listing header
    INSERT INTO listings.market_listings (
        product_id, instance_number, source_domain, source_url,
        listing_title, announced_text, status_text, release_year,
        release_month, release_day, colors, has_loudspeaker,
        has_3_5mm_jack, raw_payload, scrape_run_id, scraped_at
    )
    VALUES (
        v_product_id,
        COALESCE(v_instance_num, 1),
        p_source_domain,
        v_source_url,
        v_mobile_name,
        p_json->>'Announced',
        p_json->>'Status',
        COALESCE((p_json->>'Year')::SMALLINT, 2014),
        COALESCE(p_json->>'Month', 'DEC'),
        (p_json->>'Day')::SMALLINT,
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Colors', '[]'::jsonb))),
        COALESCE((p_json->'Sound'->>'Loudspeaker')::INT = 1, TRUE),
        COALESCE((p_json->'Sound'->>'3.5mm jack')::INT = 1, TRUE),
        p_json,
        p_scrape_run_id,
        NOW()
    )
    ON CONFLICT (source_url) DO UPDATE SET
        listing_title = EXCLUDED.listing_title,
        announced_text = EXCLUDED.announced_text,
        status_text = EXCLUDED.status_text,
        release_year = EXCLUDED.release_year,
        release_month = EXCLUDED.release_month,
        release_day = EXCLUDED.release_day,
        colors = EXCLUDED.colors,
        has_loudspeaker = EXCLUDED.has_loudspeaker,
        has_3_5mm_jack = EXCLUDED.has_3_5mm_jack,
        raw_payload = EXCLUDED.raw_payload,
        scrape_run_id = COALESCE(EXCLUDED.scrape_run_id, listings.market_listings.scrape_run_id),
        scraped_at = NOW()
    RETURNING listing_id INTO v_listing_id;

    -- 3. Populate listing sub-tables
    -- Network
    INSERT INTO listings.listing_network (listing_id, supports_2g, supports_3g, supports_4g, supports_5g)
    VALUES (
        v_listing_id,
        COALESCE((p_json->'Network'->>'2G')::INT = 1, TRUE),
        COALESCE((p_json->'Network'->>'3G')::INT = 1, TRUE),
        COALESCE((p_json->'Network'->>'4G')::INT = 1, FALSE),
        COALESCE((p_json->'Network'->>'5G')::INT = 1, FALSE)
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        supports_2g = EXCLUDED.supports_2g,
        supports_3g = EXCLUDED.supports_3g,
        supports_4g = EXCLUDED.supports_4g,
        supports_5g = EXCLUDED.supports_5g;

    -- Body
    INSERT INTO listings.listing_body (
        listing_id, dim_length_mm, dim_width_mm, dim_depth_mm, weight_grams,
        build_materials, has_normal_sim, has_nano_sim, has_esim,
        ip_rating, is_water_resistant, is_dust_resistant
    )
    VALUES (
        v_listing_id,
        COALESCE((p_json->'Body'->'Dimensions'->>'DimensionA')::NUMERIC, 50.0),
        COALESCE((p_json->'Body'->'Dimensions'->>'DimensionB')::NUMERIC, 50.0),
        COALESCE((p_json->'Body'->'Dimensions'->>'DimensionC')::NUMERIC, 5.0),
        COALESCE((p_json->'Body'->>'Weight')::NUMERIC, 25.0),
        p_json->'Body'->>'Build',
        COALESCE((p_json->'Body'->>'Normal-SIM')::INT = 1, FALSE),
        COALESCE((p_json->'Body'->>'Nano-SIM')::INT = 1, TRUE),
        COALESCE((p_json->'Body'->>'E-SIM')::INT = 1, FALSE),
        p_json->'Body'->>'Resistance-Standard',
        COALESCE((p_json->'Body'->>'Resistance-Water')::INT = 1, FALSE),
        COALESCE((p_json->'Body'->>'Resistance-Dust')::INT = 1, TRUE)
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        dim_length_mm = EXCLUDED.dim_length_mm,
        dim_width_mm = EXCLUDED.dim_width_mm,
        dim_depth_mm = EXCLUDED.dim_depth_mm,
        weight_grams = EXCLUDED.weight_grams,
        build_materials = EXCLUDED.build_materials,
        has_normal_sim = EXCLUDED.has_normal_sim,
        has_nano_sim = EXCLUDED.has_nano_sim,
        has_esim = EXCLUDED.has_esim,
        ip_rating = EXCLUDED.ip_rating,
        is_water_resistant = EXCLUDED.is_water_resistant,
        is_dust_resistant = EXCLUDED.is_dust_resistant;

    -- Display
    INSERT INTO listings.listing_display (
        listing_id, screen_technology, refresh_rate_hz, peak_brightness_nits,
        resolution_width, resolution_height, aspect_ratio, pixel_density_ppi, screen_protection
    )
    VALUES (
        v_listing_id,
        COALESCE(p_json->'Display'->>'Screen', 'LCD'),
        COALESCE((p_json->'Display'->>'Refresh-Rate')::INT, 60),
        COALESCE((p_json->'Display'->>'Brightness')::INT, 60),
        COALESCE((p_json->'Display'->>'ResolutionA')::INT, 240),
        COALESCE((p_json->'Display'->>'ResolutionB')::INT, 240),
        p_json->'Display'->>'Ratio',
        (p_json->'Display'->>'Pixel-Density')::INT,
        p_json->'Display'->>'Protection'
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        screen_technology = EXCLUDED.screen_technology,
        refresh_rate_hz = EXCLUDED.refresh_rate_hz,
        peak_brightness_nits = EXCLUDED.peak_brightness_nits,
        resolution_width = EXCLUDED.resolution_width,
        resolution_height = EXCLUDED.resolution_height,
        aspect_ratio = EXCLUDED.aspect_ratio,
        pixel_density_ppi = EXCLUDED.pixel_density_ppi,
        screen_protection = EXCLUDED.screen_protection;

    -- Platform
    INSERT INTO listings.listing_platform (
        listing_id, operating_system, chipset_name, chipset_node_nm, cpu_description, gpu_name
    )
    VALUES (
        v_listing_id,
        p_json->'Platform'->>'OS',
        p_json->'Platform'->>'Chipset',
        (p_json->'Platform'->>'Chipset-Size')::INT,
        p_json->'Platform'->>'CPU',
        p_json->'Platform'->>'GPU'
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        operating_system = EXCLUDED.operating_system,
        chipset_name = EXCLUDED.chipset_name,
        chipset_node_nm = EXCLUDED.chipset_node_nm,
        cpu_description = EXCLUDED.cpu_description,
        gpu_name = EXCLUDED.gpu_name;

    -- Memory
    INSERT INTO listings.listing_memory (listing_id, card_slot, storage_ram_variants, technology)
    VALUES (
        v_listing_id,
        p_json->'Memory'->>'Card slot',
        COALESCE(p_json->'Memory'->'Types', '[[0,0]]'::jsonb),
        p_json->'Memory'->>'Technology'
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        card_slot = EXCLUDED.card_slot,
        storage_ram_variants = EXCLUDED.storage_ram_variants,
        technology = EXCLUDED.technology;

    -- Camera Main
    INSERT INTO listings.listing_camera_main (listing_id, sensor_specs, photo_features, video_modes)
    VALUES (
        v_listing_id,
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Main Camera'->'Specifications', '[]'::jsonb))),
        p_json->'Main Camera'->>'Features',
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Main Camera'->'Video', '[]'::jsonb)))
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        sensor_specs = EXCLUDED.sensor_specs,
        photo_features = EXCLUDED.photo_features,
        video_modes = EXCLUDED.video_modes;

    -- Camera Selfie
    INSERT INTO listings.listing_camera_selfie (listing_id, sensor_specs, video_modes)
    VALUES (
        v_listing_id,
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Selfie Camera'->'Specifications', '[]'::jsonb))),
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Selfie Camera'->'Video', '[]'::jsonb)))
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        sensor_specs = EXCLUDED.sensor_specs,
        video_modes = EXCLUDED.video_modes;

    -- Connectivity / Features
    INSERT INTO listings.listing_connectivity (
        listing_id, wifi_standards, bluetooth_version, positioning_systems,
        has_nfc, has_infrared, has_fm_radio, has_usb_a, has_usb_b,
        has_micro_usb, has_usb_c, has_fp_rear, has_fp_side, has_fp_under_display
    )
    VALUES (
        v_listing_id,
        p_json->'Features'->>'WLAN',
        p_json->'Features'->>'Bluetooth',
        p_json->'Features'->>'Positioning',
        COALESCE((p_json->'Features'->>'NFC')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'Infrared port')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'Radio')::INT = 1, TRUE),
        COALESCE((p_json->'Features'->>'USB-A')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'USB-B')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'Micro-USB')::INT = 1, TRUE),
        COALESCE((p_json->'Features'->>'USB-C')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'BackFingerPrint')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'SideFingerPrint')::INT = 1, FALSE),
        COALESCE((p_json->'Features'->>'InDisplayFingerPrint')::INT = 1, FALSE)
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        wifi_standards = EXCLUDED.wifi_standards,
        bluetooth_version = EXCLUDED.bluetooth_version,
        positioning_systems = EXCLUDED.positioning_systems,
        has_nfc = EXCLUDED.has_nfc,
        has_infrared = EXCLUDED.has_infrared,
        has_fm_radio = EXCLUDED.has_fm_radio,
        has_usb_a = EXCLUDED.has_usb_a,
        has_usb_b = EXCLUDED.has_usb_b,
        has_micro_usb = EXCLUDED.has_micro_usb,
        has_usb_c = EXCLUDED.has_usb_c,
        has_fp_rear = EXCLUDED.has_fp_rear,
        has_fp_side = EXCLUDED.has_fp_side,
        has_fp_under_display = EXCLUDED.has_fp_under_display;

    -- Battery
    INSERT INTO listings.listing_battery (listing_id, capacity_mah, has_wireless_charging, charging_specs)
    VALUES (
        v_listing_id,
        COALESCE((p_json->'Battery'->>'Capacity')::INT, 0),
        COALESCE((p_json->'Battery'->>'WirelessCharging')::INT = 1, FALSE),
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Battery'->'Charging', '[]'::jsonb)))
    )
    ON CONFLICT (listing_id) DO UPDATE SET
        capacity_mah = EXCLUDED.capacity_mah,
        has_wireless_charging = EXCLUDED.has_wireless_charging,
        charging_specs = EXCLUDED.charging_specs;

    -- 4. Parse & store structured prices
    IF p_json->'Price' IS NOT NULL AND jsonb_typeof(p_json->'Price') = 'array' THEN
        DELETE FROM listings.listing_prices WHERE listing_id = v_listing_id;
        
        FOR v_price_elem IN SELECT * FROM jsonb_array_elements(p_json->'Price')
        LOOP
            v_price_val := (v_price_elem#>>'{}')::NUMERIC;
            IF v_price_val IS NOT NULL AND v_price_val > 0 THEN
                -- Assign currency by array index standard: [USD, EUR, GBP, PKR] or default PKR
                IF v_price_idx = 0 THEN v_currency := 'USD';
                ELSIF v_price_idx = 1 THEN v_currency := 'EUR';
                ELSIF v_price_idx = 2 THEN v_currency := 'GBP';
                ELSIF v_price_idx = 3 THEN v_currency := 'PKR';
                ELSE v_currency := 'PKR';
                END IF;

                INSERT INTO listings.listing_prices (listing_id, currency_code, amount, price_index)
                VALUES (v_listing_id, v_currency, v_price_val, v_price_idx)
                ON CONFLICT (listing_id, currency_code, price_index) DO UPDATE
                    SET amount = EXCLUDED.amount;
            END IF;
            v_price_idx := v_price_idx + 1;
        END LOOP;
    END IF;

    -- 5. Canonical Specs Promotion (GSMArena takes priority, or first source establishes specs)
    v_is_canonical := (p_source_domain = 'gsmarena.com' OR p_source_domain = 'original');
    SELECT EXISTS(SELECT 1 FROM specs.product_specs WHERE product_id = v_product_id) INTO v_has_canonical_specs;

    IF v_is_canonical OR NOT v_has_canonical_specs THEN
        -- Product Specs Header
        INSERT INTO specs.product_specs (
            product_id, release_year, release_month, release_day,
            announced_text, status_text, colors, has_loudspeaker,
            has_3_5mm_jack, specs_source, last_updated
        )
        VALUES (
            v_product_id,
            COALESCE((p_json->>'Year')::SMALLINT, 2014),
            COALESCE(p_json->>'Month', 'DEC'),
            (p_json->>'Day')::SMALLINT,
            p_json->>'Announced',
            p_json->>'Status',
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Colors', '[]'::jsonb))),
            COALESCE((p_json->'Sound'->>'Loudspeaker')::INT = 1, TRUE),
            COALESCE((p_json->'Sound'->>'3.5mm jack')::INT = 1, TRUE),
            p_source_domain,
            NOW()
        )
        ON CONFLICT (product_id) DO UPDATE SET
            release_year = EXCLUDED.release_year,
            release_month = EXCLUDED.release_month,
            release_day = EXCLUDED.release_day,
            announced_text = EXCLUDED.announced_text,
            status_text = EXCLUDED.status_text,
            colors = EXCLUDED.colors,
            has_loudspeaker = EXCLUDED.has_loudspeaker,
            has_3_5mm_jack = EXCLUDED.has_3_5mm_jack,
            specs_source = EXCLUDED.specs_source,
            last_updated = NOW();

        -- Spec Network
        INSERT INTO specs.spec_network (product_id, supports_2g, supports_3g, supports_4g, supports_5g)
        VALUES (
            v_product_id,
            COALESCE((p_json->'Network'->>'2G')::INT = 1, TRUE),
            COALESCE((p_json->'Network'->>'3G')::INT = 1, TRUE),
            COALESCE((p_json->'Network'->>'4G')::INT = 1, FALSE),
            COALESCE((p_json->'Network'->>'5G')::INT = 1, FALSE)
        )
        ON CONFLICT (product_id) DO UPDATE SET
            supports_2g = EXCLUDED.supports_2g,
            supports_3g = EXCLUDED.supports_3g,
            supports_4g = EXCLUDED.supports_4g,
            supports_5g = EXCLUDED.supports_5g;

        -- Spec Body
        INSERT INTO specs.spec_body (
            product_id, dim_length_mm, dim_width_mm, dim_depth_mm, weight_grams,
            build_materials, has_normal_sim, has_nano_sim, has_esim,
            ip_rating, is_water_resistant, is_dust_resistant
        )
        VALUES (
            v_product_id,
            COALESCE((p_json->'Body'->'Dimensions'->>'DimensionA')::NUMERIC, 50.0),
            COALESCE((p_json->'Body'->'Dimensions'->>'DimensionB')::NUMERIC, 50.0),
            COALESCE((p_json->'Body'->'Dimensions'->>'DimensionC')::NUMERIC, 5.0),
            COALESCE((p_json->'Body'->>'Weight')::NUMERIC, 25.0),
            p_json->'Body'->>'Build',
            COALESCE((p_json->'Body'->>'Normal-SIM')::INT = 1, FALSE),
            COALESCE((p_json->'Body'->>'Nano-SIM')::INT = 1, TRUE),
            COALESCE((p_json->'Body'->>'E-SIM')::INT = 1, FALSE),
            p_json->'Body'->>'Resistance-Standard',
            COALESCE((p_json->'Body'->>'Resistance-Water')::INT = 1, FALSE),
            COALESCE((p_json->'Body'->>'Resistance-Dust')::INT = 1, TRUE)
        )
        ON CONFLICT (product_id) DO UPDATE SET
            dim_length_mm = EXCLUDED.dim_length_mm,
            dim_width_mm = EXCLUDED.dim_width_mm,
            dim_depth_mm = EXCLUDED.dim_depth_mm,
            weight_grams = EXCLUDED.weight_grams,
            build_materials = EXCLUDED.build_materials,
            has_normal_sim = EXCLUDED.has_normal_sim,
            has_nano_sim = EXCLUDED.has_nano_sim,
            has_esim = EXCLUDED.has_esim,
            ip_rating = EXCLUDED.ip_rating,
            is_water_resistant = EXCLUDED.is_water_resistant,
            is_dust_resistant = EXCLUDED.is_dust_resistant;

        -- Spec Display
        INSERT INTO specs.spec_display (
            product_id, screen_technology, refresh_rate_hz, peak_brightness_nits,
            resolution_width, resolution_height, aspect_ratio, pixel_density_ppi, screen_protection
        )
        VALUES (
            v_product_id,
            COALESCE(p_json->'Display'->>'Screen', 'LCD'),
            COALESCE((p_json->'Display'->>'Refresh-Rate')::INT, 60),
            COALESCE((p_json->'Display'->>'Brightness')::INT, 60),
            COALESCE((p_json->'Display'->>'ResolutionA')::INT, 240),
            COALESCE((p_json->'Display'->>'ResolutionB')::INT, 240),
            p_json->'Display'->>'Ratio',
            (p_json->'Display'->>'Pixel-Density')::INT,
            p_json->'Display'->>'Protection'
        )
        ON CONFLICT (product_id) DO UPDATE SET
            screen_technology = EXCLUDED.screen_technology,
            refresh_rate_hz = EXCLUDED.refresh_rate_hz,
            peak_brightness_nits = EXCLUDED.peak_brightness_nits,
            resolution_width = EXCLUDED.resolution_width,
            resolution_height = EXCLUDED.resolution_height,
            aspect_ratio = EXCLUDED.aspect_ratio,
            pixel_density_ppi = EXCLUDED.pixel_density_ppi,
            screen_protection = EXCLUDED.screen_protection;

        -- Spec Platform
        INSERT INTO specs.spec_platform (
            product_id, operating_system, chipset_name, chipset_node_nm, cpu_description, gpu_name
        )
        VALUES (
            v_product_id,
            p_json->'Platform'->>'OS',
            p_json->'Platform'->>'Chipset',
            (p_json->'Platform'->>'Chipset-Size')::INT,
            p_json->'Platform'->>'CPU',
            p_json->'Platform'->>'GPU'
        )
        ON CONFLICT (product_id) DO UPDATE SET
            operating_system = EXCLUDED.operating_system,
            chipset_name = EXCLUDED.chipset_name,
            chipset_node_nm = EXCLUDED.chipset_node_nm,
            cpu_description = EXCLUDED.cpu_description,
            gpu_name = EXCLUDED.gpu_name;

        -- Spec Memory
        INSERT INTO specs.spec_memory (product_id, card_slot, storage_ram_variants, technology)
        VALUES (
            v_product_id,
            p_json->'Memory'->>'Card slot',
            COALESCE(p_json->'Memory'->'Types', '[[0,0]]'::jsonb),
            p_json->'Memory'->>'Technology'
        )
        ON CONFLICT (product_id) DO UPDATE SET
            card_slot = EXCLUDED.card_slot,
            storage_ram_variants = EXCLUDED.storage_ram_variants,
            technology = EXCLUDED.technology;

        -- Spec Camera Main
        INSERT INTO specs.spec_camera_main (product_id, sensor_specs, photo_features, video_modes)
        VALUES (
            v_product_id,
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Main Camera'->'Specifications', '[]'::jsonb))),
            p_json->'Main Camera'->>'Features',
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Main Camera'->'Video', '[]'::jsonb)))
        )
        ON CONFLICT (product_id) DO UPDATE SET
            sensor_specs = EXCLUDED.sensor_specs,
            photo_features = EXCLUDED.photo_features,
            video_modes = EXCLUDED.video_modes;

        -- Spec Camera Selfie
        INSERT INTO specs.spec_camera_selfie (product_id, sensor_specs, video_modes)
        VALUES (
            v_product_id,
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Selfie Camera'->'Specifications', '[]'::jsonb))),
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Selfie Camera'->'Video', '[]'::jsonb)))
        )
        ON CONFLICT (product_id) DO UPDATE SET
            sensor_specs = EXCLUDED.sensor_specs,
            video_modes = EXCLUDED.video_modes;

        -- Spec Connectivity
        INSERT INTO specs.spec_connectivity (
            product_id, wifi_standards, bluetooth_version, positioning_systems,
            has_nfc, has_infrared, has_fm_radio, has_usb_a, has_usb_b,
            has_micro_usb, has_usb_c, has_fp_rear, has_fp_side, has_fp_under_display
        )
        VALUES (
            v_product_id,
            p_json->'Features'->>'WLAN',
            p_json->'Features'->>'Bluetooth',
            p_json->'Features'->>'Positioning',
            COALESCE((p_json->'Features'->>'NFC')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'Infrared port')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'Radio')::INT = 1, TRUE),
            COALESCE((p_json->'Features'->>'USB-A')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'USB-B')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'Micro-USB')::INT = 1, TRUE),
            COALESCE((p_json->'Features'->>'USB-C')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'BackFingerPrint')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'SideFingerPrint')::INT = 1, FALSE),
            COALESCE((p_json->'Features'->>'InDisplayFingerPrint')::INT = 1, FALSE)
        )
        ON CONFLICT (product_id) DO UPDATE SET
            wifi_standards = EXCLUDED.wifi_standards,
            bluetooth_version = EXCLUDED.bluetooth_version,
            positioning_systems = EXCLUDED.positioning_systems,
            has_nfc = EXCLUDED.has_nfc,
            has_infrared = EXCLUDED.has_infrared,
            has_fm_radio = EXCLUDED.has_fm_radio,
            has_usb_a = EXCLUDED.has_usb_a,
            has_usb_b = EXCLUDED.has_usb_b,
            has_micro_usb = EXCLUDED.has_micro_usb,
            has_usb_c = EXCLUDED.has_usb_c,
            has_fp_rear = EXCLUDED.has_fp_rear,
            has_fp_side = EXCLUDED.has_fp_side,
            has_fp_under_display = EXCLUDED.has_fp_under_display;

        -- Spec Battery
        INSERT INTO specs.spec_battery (product_id, capacity_mah, has_wireless_charging, charging_specs)
        VALUES (
            v_product_id,
            COALESCE((p_json->'Battery'->>'Capacity')::INT, 0),
            COALESCE((p_json->'Battery'->>'WirelessCharging')::INT = 1, FALSE),
            ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_json->'Battery'->'Charging', '[]'::jsonb)))
        )
        ON CONFLICT (product_id) DO UPDATE SET
            capacity_mah = EXCLUDED.capacity_mah,
            has_wireless_charging = EXCLUDED.has_wireless_charging,
            charging_specs = EXCLUDED.charging_specs;
    END IF;

    -- 6. Quality & Completeness Scoring
    IF p_json->>'CompanyName' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->>'MobileName' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->>'Announced' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->>'Status' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Body'->>'Weight' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Body'->'Dimensions'->>'DimensionA' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Display'->>'Screen' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Display'->>'Refresh-Rate' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Display'->>'ResolutionA' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Platform'->>'OS' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Platform'->>'Chipset' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Platform'->>'CPU' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Platform'->>'GPU' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Memory'->>'Card slot' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Memory'->'Types' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Main Camera'->'Specifications' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Selfie Camera'->'Specifications' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Battery'->>'Capacity' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;
    IF p_json->'Battery'->'Charging' IS NOT NULL THEN v_fields_populated := v_fields_populated + 1; END IF;

    v_completeness := ROUND((v_fields_populated::NUMERIC / v_fields_total::NUMERIC) * 100.0, 2);

    INSERT INTO metadata.data_quality (
        product_id, listing_id, source_domain, completeness_pct, fields_populated, fields_total
    )
    VALUES (
        v_product_id, v_listing_id, p_source_domain, v_completeness, v_fields_populated, v_fields_total
    );

    RETURN v_listing_id;
EXCEPTION WHEN OTHERS THEN
    INSERT INTO metadata.etl_rejects (
        scrape_run_id, source_domain, source_url, source_file,
        reject_reason, reject_detail, raw_payload
    )
    VALUES (
        p_scrape_run_id,
        p_source_domain,
        v_source_url,
        p_source_file,
        'INGESTION_ERROR',
        SQLERRM,
        p_json
    );
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION etl.ingest_template_v2_json IS
'Parses a clean template_v2 JSON, links to catalog, stores listing & specs, structured prices, and quality scores.';


-- =============================================================================
-- 3. BATCH STAGING INGESTION PROCEDURE (RLS Hardened)
-- =============================================================================

CREATE OR REPLACE PROCEDURE etl.process_staging_batch(
    p_batch_size INT DEFAULT 1000,
    p_scrape_run_id BIGINT DEFAULT NULL
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = catalog, specs, listings, metadata, staging, analytics, public
AS $$
DECLARE
    r RECORD;
    v_res BIGINT;
    v_succeeded INT := 0;
    v_failed INT := 0;
BEGIN
    FOR r IN
        SELECT staging_id, source_domain, source_file, payload
        FROM staging.raw_json_records
        WHERE status = 'pending'
        ORDER BY staging_id
        LIMIT p_batch_size
    LOOP
        v_res := etl.ingest_template_v2_json(
            r.payload,
            r.source_domain,
            r.source_file,
            p_scrape_run_id
        );

        IF v_res IS NOT NULL THEN
            UPDATE staging.raw_json_records
            SET status = 'processed', processed_at = NOW()
            WHERE staging_id = r.staging_id;
            v_succeeded := v_succeeded + 1;
        ELSE
            UPDATE staging.raw_json_records
            SET status = 'failed', processed_at = NOW()
            WHERE staging_id = r.staging_id;
            v_failed := v_failed + 1;
        END IF;
    END LOOP;

    IF p_scrape_run_id IS NOT NULL THEN
        UPDATE metadata.scrape_runs
        SET records_processed = records_processed + (v_succeeded + v_failed),
            records_succeeded = records_succeeded + v_succeeded,
            records_failed = records_failed + v_failed,
            finished_at = NOW(),
            run_status = CASE WHEN v_failed = 0 THEN 'completed' ELSE 'completed_with_errors' END
        WHERE run_id = p_scrape_run_id;
    END IF;
END;
$$;


-- =============================================================================
-- 4. ANALYTICS & BI VIEWS (Security Invoker)
-- =============================================================================

-- View 1: analytics.v_canonical_products (Full Canonical Specs Flattened)
CREATE OR REPLACE VIEW analytics.v_canonical_products
WITH (security_invoker = true)
AS
SELECT
    p.product_id,
    c.company_name,
    p.mobile_name,
    p.product_slug,
    p.created_by_source,
    s.release_year,
    s.release_month,
    s.release_day,
    s.announced_text,
    s.status_text,
    s.colors,
    s.has_loudspeaker,
    s.has_3_5mm_jack,
    s.specs_source,
    -- Network
    n.supports_2g, n.supports_3g, n.supports_4g, n.supports_5g,
    -- Body
    b.dim_length_mm, b.dim_width_mm, b.dim_depth_mm, b.weight_grams,
    b.build_materials, b.has_normal_sim, b.has_nano_sim, b.has_esim,
    b.ip_rating, b.is_water_resistant, b.is_dust_resistant,
    -- Display
    d.screen_technology, d.refresh_rate_hz, d.peak_brightness_nits,
    d.resolution_width, d.resolution_height, d.aspect_ratio,
    d.pixel_density_ppi, d.screen_protection,
    -- Platform
    pl.operating_system, pl.chipset_name, pl.chipset_node_nm,
    pl.cpu_description, pl.gpu_name,
    -- Memory
    m.card_slot, m.storage_ram_variants, m.technology AS memory_technology,
    -- Cameras
    cm.sensor_specs AS main_camera_specs, cm.photo_features AS main_camera_features, cm.video_modes AS main_camera_video,
    cs.sensor_specs AS selfie_camera_specs, cs.video_modes AS selfie_camera_video,
    -- Connectivity
    cn.wifi_standards, cn.bluetooth_version, cn.positioning_systems,
    cn.has_nfc, cn.has_infrared, cn.has_fm_radio, cn.has_usb_a,
    cn.has_usb_b, cn.has_micro_usb, cn.has_usb_c,
    cn.has_fp_rear, cn.has_fp_side, cn.has_fp_under_display,
    -- Battery
    bat.capacity_mah, bat.has_wireless_charging, bat.charging_specs
FROM catalog.products p
JOIN catalog.companies c ON c.company_id = p.company_id
LEFT JOIN specs.product_specs s ON s.product_id = p.product_id
LEFT JOIN specs.spec_network n ON n.product_id = p.product_id
LEFT JOIN specs.spec_body b ON b.product_id = p.product_id
LEFT JOIN specs.spec_display d ON d.product_id = p.product_id
LEFT JOIN specs.spec_platform pl ON pl.product_id = p.product_id
LEFT JOIN specs.spec_memory m ON m.product_id = p.product_id
LEFT JOIN specs.spec_camera_main cm ON cm.product_id = p.product_id
LEFT JOIN specs.spec_camera_selfie cs ON cs.product_id = p.product_id
LEFT JOIN specs.spec_connectivity cn ON cn.product_id = p.product_id
LEFT JOIN specs.spec_battery bat ON bat.product_id = p.product_id;


-- View 2: analytics.v_market_listings_full (All Scraped Marketplace Listings)
CREATE OR REPLACE VIEW analytics.v_market_listings_full
WITH (security_invoker = true)
AS
SELECT
    ml.listing_id,
    ml.product_id,
    c.company_name,
    p.mobile_name AS canonical_product_name,
    ml.instance_number,
    ml.source_domain,
    ml.source_url,
    ml.listing_title,
    ml.release_year,
    ml.release_month,
    ml.scraped_at,
    -- Prices aggregated as JSON summary
    COALESCE(
        (SELECT jsonb_object_agg(currency_code, amount)
         FROM listings.listing_prices lp
         WHERE lp.listing_id = ml.listing_id),
        '{}'::jsonb
    ) AS prices,
    -- Sub-specs
    d.screen_technology, d.refresh_rate_hz, d.resolution_width || 'x' || d.resolution_height AS resolution,
    pl.chipset_name, pl.operating_system,
    m.storage_ram_variants,
    b.weight_grams,
    bat.capacity_mah
FROM listings.market_listings ml
JOIN catalog.products p ON p.product_id = ml.product_id
JOIN catalog.companies c ON c.company_id = p.company_id
LEFT JOIN listings.listing_display d ON d.listing_id = ml.listing_id
LEFT JOIN listings.listing_platform pl ON pl.listing_id = ml.listing_id
LEFT JOIN listings.listing_memory m ON m.listing_id = ml.listing_id
LEFT JOIN listings.listing_body b ON b.listing_id = ml.listing_id
LEFT JOIN listings.listing_battery bat ON bat.listing_id = ml.listing_id;


-- View 3: analytics.v_price_comparison (Cross-Site Price Comparison per Phone)
CREATE OR REPLACE VIEW analytics.v_price_comparison
WITH (security_invoker = true)
AS
SELECT
    p.product_id,
    c.company_name,
    p.mobile_name,
    lp.currency_code,
    COUNT(DISTINCT ml.source_domain) AS sources_count,
    COUNT(ml.listing_id) AS total_listings,
    MIN(lp.amount) AS min_price,
    ROUND(AVG(lp.amount), 2) AS avg_price,
    MAX(lp.amount) AS max_price,
    (MAX(lp.amount) - MIN(lp.amount)) AS price_spread,
    jsonb_agg(
        jsonb_build_object(
            'source', ml.source_domain,
            'title', ml.listing_title,
            'url', ml.source_url,
            'price', lp.amount,
            'instance', ml.instance_number
        ) ORDER BY lp.amount ASC
    ) AS listings_detail
FROM catalog.products p
JOIN catalog.companies c ON c.company_id = p.company_id
JOIN listings.market_listings ml ON ml.product_id = p.product_id
JOIN listings.listing_prices lp ON lp.listing_id = ml.listing_id
WHERE lp.amount > 0
GROUP BY p.product_id, c.company_name, p.mobile_name, lp.currency_code;


-- View 4: analytics.v_spec_discrepancies (Cross-Site Specs Discrepancies)
CREATE OR REPLACE VIEW analytics.v_spec_discrepancies
WITH (security_invoker = true)
AS
SELECT
    p.product_id,
    c.company_name,
    p.mobile_name,
    ml.source_domain,
    ml.listing_title,
    -- Canonical vs Listing Battery
    s_bat.capacity_mah AS canonical_battery_mah,
    l_bat.capacity_mah AS listing_battery_mah,
    (s_bat.capacity_mah <> l_bat.capacity_mah) AS battery_discrepancy,
    -- Canonical vs Listing Screen
    s_d.screen_technology AS canonical_screen,
    l_d.screen_technology AS listing_screen,
    (s_d.screen_technology <> l_d.screen_technology) AS screen_discrepancy,
    -- Canonical vs Listing Refresh Rate
    s_d.refresh_rate_hz AS canonical_refresh_hz,
    l_d.refresh_rate_hz AS listing_refresh_hz,
    (s_d.refresh_rate_hz <> l_d.refresh_rate_hz) AS refresh_discrepancy,
    -- Canonical vs Listing Memory Variants
    s_m.storage_ram_variants AS canonical_memory,
    l_m.storage_ram_variants AS listing_memory
FROM catalog.products p
JOIN catalog.companies c ON c.company_id = p.company_id
JOIN specs.product_specs s ON s.product_id = p.product_id
LEFT JOIN specs.spec_battery s_bat ON s_bat.product_id = p.product_id
LEFT JOIN specs.spec_display s_d ON s_d.product_id = p.product_id
LEFT JOIN specs.spec_memory s_m ON s_m.product_id = p.product_id
JOIN listings.market_listings ml ON ml.product_id = p.product_id
LEFT JOIN listings.listing_battery l_bat ON l_bat.listing_id = ml.listing_id
LEFT JOIN listings.listing_display l_d ON l_d.listing_id = ml.listing_id
LEFT JOIN listings.listing_memory l_m ON l_m.listing_id = ml.listing_id
WHERE ml.source_domain NOT IN ('gsmarena.com', 'original');


-- View 5: analytics.v_site_summary (Site Aggregate Overview)
CREATE OR REPLACE VIEW analytics.v_site_summary
WITH (security_invoker = true)
AS
SELECT
    ml.source_domain,
    COUNT(DISTINCT ml.product_id) AS distinct_products_covered,
    COUNT(ml.listing_id) AS total_listings,
    ROUND(AVG(dq.completeness_pct), 2) AS avg_data_completeness_pct,
    MIN(ml.scraped_at) AS first_scraped_at,
    MAX(ml.scraped_at) AS last_scraped_at
FROM listings.market_listings ml
LEFT JOIN metadata.data_quality dq ON dq.listing_id = ml.listing_id
GROUP BY ml.source_domain;


-- =============================================================================
-- 5. FUNCTION & PROCEDURE PERMISSIONS
-- =============================================================================

GRANT EXECUTE ON FUNCTION catalog.slugify(TEXT) TO anon, authenticated, service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA catalog, etl TO service_role, postgres;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA etl TO service_role, postgres;
