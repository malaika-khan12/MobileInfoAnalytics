-- MobileInfoAnalytics Redshift ETL and analytics v1
-- Run db/schema_v1.sql before this file.
--
-- COPY lands rows in staging.phone_records.  These procedures perform bulk,
-- set-based upserts.  No marketplace payload is trusted for data_snapshot or
-- data_snapshot_detail; those values always come from original.central_info.

-- -------------------------------------------------------------------------
-- GSMArena canonical load
-- -------------------------------------------------------------------------

CREATE OR REPLACE PROCEDURE etl.load_original()
AS $$
BEGIN
    DROP TABLE IF EXISTS _original_work;

    CREATE TEMP TABLE _original_work AS
    SELECT
        r.*,
        COALESCE(
            c.serial_number,
            b.max_serial + ROW_NUMBER() OVER (ORDER BY r.source_url)
        ) AS assigned_serial
    FROM (
        SELECT *
        FROM staging.phone_records
        WHERE source_schema = 'original'
          AND mobile_name IS NOT NULL
          AND source_url IS NOT NULL
          AND data_snapshot BETWEEN 1900 AND 2100
          AND data_snapshot_detail ~ '^(0[1-9]|1[0-2])(-([0-2][0-9]|3[01]))?$'
          AND snapshot_source IN ('announced', 'status', 'current_utc')
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY source_url ORDER BY record_key
        ) = 1
    ) r
    LEFT JOIN original.central_info c
      ON c.url = r.source_url
      OR LOWER(TRIM(c.name)) = LOWER(TRIM(r.mobile_name))
    CROSS JOIN (
        SELECT COALESCE(MAX(serial_number), 0) AS max_serial
        FROM original.central_info
    ) b
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY r.source_url
        ORDER BY CASE WHEN c.url = r.source_url THEN 0 ELSE 1 END,
                 c.serial_number
    ) = 1;

    UPDATE warehouse.etl_rejects e
       SET resolved_at = GETDATE(),
           resolution_detail = 'Resolved by a later valid GSMArena snapshot'
      FROM _original_work w
     WHERE e.record_key = w.record_key
       AND e.reason_code = 'INVALID_CANONICAL_SNAPSHOT'
       AND e.resolved_at IS NULL;

    INSERT INTO warehouse.etl_rejects (
        record_key, source_schema, source_url, source_file,
        reason_code, reason_detail, payload
    )
    SELECT
        r.record_key, r.source_schema, r.source_url, r.source_file,
        'INVALID_CANONICAL_SNAPSHOT',
        'GSMArena requires YYYY plus MM or MM-DD from Announced, Status, or UTC fallback',
        r.payload_json
    FROM staging.phone_records r
    WHERE r.source_schema = 'original'
      AND NOT EXISTS (
          SELECT 1 FROM _original_work w WHERE w.record_key = r.record_key
      )
      AND NOT EXISTS (
          SELECT 1
          FROM warehouse.etl_rejects e
          WHERE e.record_key = r.record_key
            AND e.reason_code = 'INVALID_CANONICAL_SNAPSHOT'
            AND e.resolved_at IS NULL
      );

    MERGE INTO original.central_info AS target
    USING _original_work AS source
       ON target.serial_number = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        data_snapshot = source.data_snapshot,
        data_snapshot_detail = source.data_snapshot_detail,
        snapshot_source = source.snapshot_source,
        name = source.mobile_name,
        url = source.source_url,
        sound_loudspeaker = source.sound_loudspeaker,
        sound_cable_jack = source.sound_cable_jack,
        colors = source.colors_json,
        weight = COALESCE(source.exposure_weight, 'Weight Unknown'),
        price = source.prices_json
    WHEN NOT MATCHED THEN INSERT (
        serial_number, data_snapshot, data_snapshot_detail, snapshot_source,
        name, url, network_id, launch_id, body_id, display_id, platform_id,
        memory_id, camera_back_id, camera_front_id, sound_loudspeaker,
        sound_cable_jack, features_id, battery_id, colors, weight, price
    ) VALUES (
        source.assigned_serial, source.data_snapshot,
        source.data_snapshot_detail, source.snapshot_source,
        source.mobile_name, source.source_url,
        source.assigned_serial, source.assigned_serial, source.assigned_serial,
        source.assigned_serial, source.assigned_serial, source.assigned_serial,
        source.assigned_serial, source.assigned_serial,
        source.sound_loudspeaker, source.sound_cable_jack,
        source.assigned_serial, source.assigned_serial, source.colors_json,
        COALESCE(source.exposure_weight, 'Weight Unknown'), source.prices_json
    );

    MERGE INTO original.network AS target
    USING _original_work AS source
       ON target.network_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        "2g" = source.network_2g, "3g" = source.network_3g,
        "4g" = source.network_4g, "5g" = source.network_5g
    WHEN NOT MATCHED THEN INSERT (network_id, "2g", "3g", "4g", "5g")
    VALUES (source.assigned_serial, source.network_2g, source.network_3g,
            source.network_4g, source.network_5g);

    MERGE INTO original.launch AS target
    USING _original_work AS source
       ON target.launch_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        announced = source.launch_announced, status = source.launch_status
    WHEN NOT MATCHED THEN INSERT (launch_id, announced, status)
    VALUES (source.assigned_serial, source.launch_announced, source.launch_status);

    MERGE INTO original.body AS target
    USING _original_work AS source
       ON target.body_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        dimensions = source.body_dimensions, weight = source.body_weight,
        build = source.body_build, sim = source.body_sim,
        protection = source.body_protection
    WHEN NOT MATCHED THEN INSERT
        (body_id, dimensions, weight, build, sim, protection)
    VALUES (source.assigned_serial, source.body_dimensions, source.body_weight,
            source.body_build, source.body_sim, source.body_protection);

    MERGE INTO original.display AS target
    USING _original_work AS source
       ON target.display_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        type = source.display_type, size = source.display_size,
        resolution = source.display_resolution,
        protection = source.display_protection
    WHEN NOT MATCHED THEN INSERT
        (display_id, type, size, resolution, protection)
    VALUES (source.assigned_serial, source.display_type, source.display_size,
            source.display_resolution, source.display_protection);

    MERGE INTO original.platform AS target
    USING _original_work AS source
       ON target.platform_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        os = source.platform_os, chipset = source.platform_chipset,
        cpu = source.platform_cpu, gpu = source.platform_gpu
    WHEN NOT MATCHED THEN INSERT (platform_id, os, chipset, cpu, gpu)
    VALUES (source.assigned_serial, source.platform_os, source.platform_chipset,
            source.platform_cpu, source.platform_gpu);

    MERGE INTO original.memory AS target
    USING _original_work AS source
       ON target.memory_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        card_slot = source.memory_card_slot,
        technology = source.memory_technology,
        types = source.memory_types_json
    WHEN NOT MATCHED THEN INSERT (memory_id, card_slot, technology, types)
    VALUES (source.assigned_serial, source.memory_card_slot,
            source.memory_technology, source.memory_types_json);

    MERGE INTO original.camera_back AS target
    USING _original_work AS source
       ON target.camera_back_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        specifications = source.main_camera_specifications_json,
        features = source.main_camera_features,
        video = source.main_camera_video_json
    WHEN NOT MATCHED THEN INSERT
        (camera_back_id, specifications, features, video)
    VALUES (source.assigned_serial, source.main_camera_specifications_json,
            source.main_camera_features, source.main_camera_video_json);

    MERGE INTO original.camera_front AS target
    USING _original_work AS source
       ON target.camera_front_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        specifications = source.selfie_camera_specifications_json,
        features = source.selfie_camera_features,
        video = source.selfie_camera_video_json
    WHEN NOT MATCHED THEN INSERT
        (camera_front_id, specifications, features, video)
    VALUES (source.assigned_serial, source.selfie_camera_specifications_json,
            source.selfie_camera_features, source.selfie_camera_video_json);

    MERGE INTO original.features AS target
    USING _original_work AS source
       ON target.features_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        wlan = source.features_wlan,
        bluetooth = source.features_bluetooth,
        positioning = source.features_positioning,
        nfc = source.features_nfc,
        infrared_port = source.features_infrared_port,
        radio = source.features_radio,
        usb = source.features_usb,
        back_finger_print = source.features_back_finger_print,
        side_finger_print = source.features_side_finger_print,
        in_display_finger_print = source.features_in_display_finger_print,
        sensors = source.features_sensors
    WHEN NOT MATCHED THEN INSERT (
        features_id, wlan, bluetooth, positioning, nfc, infrared_port,
        radio, usb, back_finger_print, side_finger_print,
        in_display_finger_print, sensors
    ) VALUES (
        source.assigned_serial, source.features_wlan,
        source.features_bluetooth, source.features_positioning,
        source.features_nfc, source.features_infrared_port,
        source.features_radio, source.features_usb,
        source.features_back_finger_print, source.features_side_finger_print,
        source.features_in_display_finger_print, source.features_sensors
    );

    MERGE INTO original.battery AS target
    USING _original_work AS source
       ON target.battery_id = source.assigned_serial
    WHEN MATCHED THEN UPDATE SET
        capacity = source.battery_capacity,
        wireless_charging = source.battery_wireless_charging,
        charging = source.battery_charging_json
    WHEN NOT MATCHED THEN INSERT
        (battery_id, capacity, wireless_charging, charging)
    VALUES (source.assigned_serial, source.battery_capacity,
            source.battery_wireless_charging, source.battery_charging_json);

    INSERT INTO warehouse.raw_ingest (
        record_key, source_schema, source_url, source_file,
        data_snapshot, data_snapshot_detail, snapshot_source,
        file_sha256, completeness_score, payload
    )
    SELECT
        w.record_key, w.source_schema, w.source_url, w.source_file,
        w.data_snapshot, w.data_snapshot_detail, w.snapshot_source,
        w.file_sha256, w.completeness_score, w.payload_json
    FROM _original_work w
    WHERE NOT EXISTS (
        SELECT 1 FROM warehouse.raw_ingest r
        WHERE r.source_schema = w.source_schema
          AND r.source_url = w.source_url
          AND r.file_sha256 = w.file_sha256
    );

    INSERT INTO warehouse.price_history (
        product_id, source_schema, source_serial_number, source_url,
        file_sha256, data_snapshot, data_snapshot_detail, amount, currency_code
    )
    SELECT
        w.assigned_serial, 'original', w.assigned_serial, w.source_url,
        w.file_sha256, w.data_snapshot, w.data_snapshot_detail,
        price_value::DECIMAL(18,2), NULL
    FROM _original_work w, w.prices_json price_value AT price_index
    WHERE price_value::DECIMAL(18,2) > 0
      AND NOT EXISTS (
          SELECT 1 FROM warehouse.price_history h
          WHERE h.source_schema = 'original'
            AND h.source_url = w.source_url
            AND h.file_sha256 = w.file_sha256
            AND h.amount = price_value::DECIMAL(18,2)
      );

    -- Canonical release corrections must propagate to every matched source.
    UPDATE daraz.secondary_info s
       SET data_snapshot = o.data_snapshot,
           data_snapshot_detail = o.data_snapshot_detail
      FROM daraz.central_info c
      JOIN original.central_info o ON o.serial_number = c.product_id
     WHERE s.serial_number = c.serial_number
       AND (s.data_snapshot <> o.data_snapshot
            OR s.data_snapshot_detail <> o.data_snapshot_detail);
    UPDATE mymobile.secondary_info s
       SET data_snapshot = o.data_snapshot,
           data_snapshot_detail = o.data_snapshot_detail
      FROM mymobile.central_info c
      JOIN original.central_info o ON o.serial_number = c.product_id
     WHERE s.serial_number = c.serial_number
       AND (s.data_snapshot <> o.data_snapshot
            OR s.data_snapshot_detail <> o.data_snapshot_detail);
    UPDATE mega.secondary_info s
       SET data_snapshot = o.data_snapshot,
           data_snapshot_detail = o.data_snapshot_detail
      FROM mega.central_info c
      JOIN original.central_info o ON o.serial_number = c.product_id
     WHERE s.serial_number = c.serial_number
       AND (s.data_snapshot <> o.data_snapshot
            OR s.data_snapshot_detail <> o.data_snapshot_detail);
    UPDATE whatamobile.secondary_info s
       SET data_snapshot = o.data_snapshot,
           data_snapshot_detail = o.data_snapshot_detail
      FROM whatamobile.central_info c
      JOIN original.central_info o ON o.serial_number = c.product_id
     WHERE s.serial_number = c.serial_number
       AND (s.data_snapshot <> o.data_snapshot
            OR s.data_snapshot_detail <> o.data_snapshot_detail);
    UPDATE whatmobile.secondary_info s
       SET data_snapshot = o.data_snapshot,
           data_snapshot_detail = o.data_snapshot_detail
      FROM whatmobile.central_info c
      JOIN original.central_info o ON o.serial_number = c.product_id
     WHERE s.serial_number = c.serial_number
       AND (s.data_snapshot <> o.data_snapshot
            OR s.data_snapshot_detail <> o.data_snapshot_detail);
END;
$$ LANGUAGE plpgsql;

-- -------------------------------------------------------------------------
-- Marketplace load.  p_source is validated before it becomes an identifier.
-- An explicit staging.product_map wins; otherwise only an exact, case-folded
-- GSMArena name is accepted.  Unmatched rows remain in raw_ingest/rejects and
-- never enter the normalized marketplace schemas.
-- -------------------------------------------------------------------------

CREATE OR REPLACE PROCEDURE etl.load_source(p_source VARCHAR)
AS $$
DECLARE
    s VARCHAR(128);
BEGIN
    IF p_source NOT IN ('daraz', 'mymobile', 'mega', 'whatamobile', 'whatmobile') THEN
        RAISE EXCEPTION 'Unsupported source schema: %', p_source;
    END IF;
    s := QUOTE_IDENT(p_source);

    DROP TABLE IF EXISTS _source_candidates;
    DROP TABLE IF EXISTS _source_work;

    EXECUTE 'CREATE TEMP TABLE _source_candidates AS
        SELECT
            r.*,
            o.serial_number AS product_id,
            o.data_snapshot AS canonical_snapshot,
            o.data_snapshot_detail AS canonical_snapshot_detail,
            si.serial_number AS existing_serial,
            ci.product_id AS existing_product_id,
            ci.instance_number AS existing_instance
        FROM staging.phone_records r
        LEFT JOIN staging.product_map pm
          ON pm.source_schema = r.source_schema
         AND pm.source_url = r.source_url
        JOIN original.central_info o
          ON (pm.product_id IS NOT NULL AND o.serial_number = pm.product_id)
          OR (pm.product_id IS NULL
              AND LOWER(TRIM(o.name)) = LOWER(TRIM(r.mobile_name)))
        LEFT JOIN ' || s || '.secondary_info si ON si.url = r.source_url
        LEFT JOIN ' || s || '.central_info ci
          ON ci.serial_number = si.serial_number
        WHERE r.source_schema = ' || QUOTE_LITERAL(p_source) || '
        QUALIFY COUNT(*) OVER (PARTITION BY r.source_url) = 1';

    INSERT INTO warehouse.raw_ingest (
        record_key, source_schema, source_url, source_file,
        data_snapshot, data_snapshot_detail, snapshot_source,
        file_sha256, completeness_score, payload
    )
    SELECT
        r.record_key, r.source_schema, r.source_url, r.source_file,
        c.canonical_snapshot, c.canonical_snapshot_detail,
        CASE WHEN c.product_id IS NULL THEN NULL ELSE 'original_database' END,
        r.file_sha256, r.completeness_score, r.payload_json
    FROM staging.phone_records r
    LEFT JOIN _source_candidates c ON c.record_key = r.record_key
    WHERE r.source_schema = p_source
      AND NOT EXISTS (
          SELECT 1 FROM warehouse.raw_ingest x
          WHERE x.source_schema = r.source_schema
            AND x.source_url = r.source_url
            AND x.file_sha256 = r.file_sha256
      );

    UPDATE warehouse.raw_ingest r
       SET data_snapshot = c.canonical_snapshot,
           data_snapshot_detail = c.canonical_snapshot_detail,
           snapshot_source = 'original_database'
      FROM _source_candidates c
     WHERE r.record_key = c.record_key
       AND r.source_schema = p_source
       AND (r.data_snapshot IS NULL
            OR r.data_snapshot_detail IS NULL
            OR r.snapshot_source IS NULL);

    UPDATE warehouse.etl_rejects e
       SET resolved_at = GETDATE(),
           resolution_detail = 'Resolved by a later canonical match'
      FROM _source_candidates c
     WHERE e.record_key = c.record_key
       AND e.reason_code = 'NO_UNIQUE_GSMARENA_MATCH'
       AND e.resolved_at IS NULL;

    INSERT INTO warehouse.etl_rejects (
        record_key, source_schema, source_url, source_file,
        reason_code, reason_detail, payload
    )
    SELECT
        r.record_key, r.source_schema, r.source_url, r.source_file,
        'NO_UNIQUE_GSMARENA_MATCH',
        'Provide one reviewed staging.product_map row or an exact GSMArena name',
        r.payload_json
    FROM staging.phone_records r
    WHERE r.source_schema = p_source
      AND NOT EXISTS (
          SELECT 1 FROM _source_candidates c WHERE c.record_key = r.record_key
      )
      AND NOT EXISTS (
          SELECT 1 FROM warehouse.etl_rejects e
          WHERE e.record_key = r.record_key
            AND e.reason_code = 'NO_UNIQUE_GSMARENA_MATCH'
            AND e.resolved_at IS NULL
      );

    EXECUTE 'CREATE TEMP TABLE _source_work AS
        SELECT
            c.*,
            COALESCE(
                c.existing_serial,
                serial_base.max_serial
                + SUM(CASE WHEN c.existing_serial IS NULL THEN 1 ELSE 0 END)
                  OVER (ORDER BY c.source_url ROWS UNBOUNDED PRECEDING)
            ) AS assigned_serial,
            CASE
                WHEN c.existing_product_id = c.product_id
                    THEN c.existing_instance
                ELSE COALESCE(instance_base.max_instance, 0)
                     + SUM(
                         CASE
                           WHEN c.existing_product_id = c.product_id THEN 0
                           ELSE 1
                         END
                       ) OVER (
                           PARTITION BY c.product_id
                           ORDER BY c.source_url ROWS UNBOUNDED PRECEDING
                       )
            END AS assigned_instance
        FROM _source_candidates c
        CROSS JOIN (
            SELECT COALESCE(MAX(serial_number), 0) AS max_serial
            FROM ' || s || '.central_info
        ) serial_base
        LEFT JOIN (
            SELECT product_id, MAX(instance_number) AS max_instance
            FROM ' || s || '.central_info
            GROUP BY product_id
        ) instance_base ON instance_base.product_id = c.product_id';

    EXECUTE 'MERGE INTO ' || s || '.central_info AS target
        USING _source_work AS source
           ON target.serial_number = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            product_id = source.product_id,
            instance_number = source.assigned_instance
        WHEN NOT MATCHED THEN INSERT
            (serial_number, product_id, instance_number)
        VALUES
            (source.assigned_serial, source.product_id, source.assigned_instance)';

    EXECUTE 'MERGE INTO ' || s || '.secondary_info AS target
        USING _source_work AS source
           ON target.serial_number = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            data_snapshot = source.canonical_snapshot,
            data_snapshot_detail = source.canonical_snapshot_detail,
            name = source.mobile_name,
            url = source.source_url,
            sound_loudspeaker = source.sound_loudspeaker,
            sound_cable_jack = source.sound_cable_jack,
            colors = source.colors_json,
            weight = COALESCE(source.exposure_weight, ''Weight Unknown''),
            price = source.prices_json
        WHEN NOT MATCHED THEN INSERT (
            serial_number, data_snapshot, data_snapshot_detail, name, url,
            network_id, launch_id, body_id, display_id, platform_id, memory_id,
            camera_back_id, camera_front_id, sound_loudspeaker,
            sound_cable_jack, features_id, battery_id, colors, weight, price
        ) VALUES (
            source.assigned_serial, source.canonical_snapshot,
            source.canonical_snapshot_detail, source.mobile_name,
            source.source_url, source.assigned_serial, source.assigned_serial,
            source.assigned_serial, source.assigned_serial,
            source.assigned_serial, source.assigned_serial,
            source.assigned_serial, source.assigned_serial,
            source.sound_loudspeaker, source.sound_cable_jack,
            source.assigned_serial, source.assigned_serial, source.colors_json,
            COALESCE(source.exposure_weight, ''Weight Unknown''),
            source.prices_json
        )';

    EXECUTE 'MERGE INTO ' || s || '.network AS target
        USING _source_work AS source ON target.network_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            "2g" = source.network_2g, "3g" = source.network_3g,
            "4g" = source.network_4g, "5g" = source.network_5g
        WHEN NOT MATCHED THEN INSERT (network_id, "2g", "3g", "4g", "5g")
        VALUES (source.assigned_serial, source.network_2g, source.network_3g,
                source.network_4g, source.network_5g)';

    EXECUTE 'MERGE INTO ' || s || '.launch AS target
        USING _source_work AS source ON target.launch_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            announced = source.launch_announced, status = source.launch_status
        WHEN NOT MATCHED THEN INSERT (launch_id, announced, status)
        VALUES (source.assigned_serial, source.launch_announced, source.launch_status)';

    EXECUTE 'MERGE INTO ' || s || '.body AS target
        USING _source_work AS source ON target.body_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            dimensions = source.body_dimensions, weight = source.body_weight,
            build = source.body_build, sim = source.body_sim,
            protection = source.body_protection
        WHEN NOT MATCHED THEN INSERT
            (body_id, dimensions, weight, build, sim, protection)
        VALUES (source.assigned_serial, source.body_dimensions, source.body_weight,
                source.body_build, source.body_sim, source.body_protection)';

    EXECUTE 'MERGE INTO ' || s || '.display AS target
        USING _source_work AS source ON target.display_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            type = source.display_type, size = source.display_size,
            resolution = source.display_resolution,
            protection = source.display_protection
        WHEN NOT MATCHED THEN INSERT
            (display_id, type, size, resolution, protection)
        VALUES (source.assigned_serial, source.display_type, source.display_size,
                source.display_resolution, source.display_protection)';

    EXECUTE 'MERGE INTO ' || s || '.platform AS target
        USING _source_work AS source ON target.platform_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            os = source.platform_os, chipset = source.platform_chipset,
            cpu = source.platform_cpu, gpu = source.platform_gpu
        WHEN NOT MATCHED THEN INSERT (platform_id, os, chipset, cpu, gpu)
        VALUES (source.assigned_serial, source.platform_os,
                source.platform_chipset, source.platform_cpu, source.platform_gpu)';

    EXECUTE 'MERGE INTO ' || s || '.memory AS target
        USING _source_work AS source ON target.memory_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            card_slot = source.memory_card_slot,
            technology = source.memory_technology,
            types = source.memory_types_json
        WHEN NOT MATCHED THEN INSERT (memory_id, card_slot, technology, types)
        VALUES (source.assigned_serial, source.memory_card_slot,
                source.memory_technology, source.memory_types_json)';

    EXECUTE 'MERGE INTO ' || s || '.camera_back AS target
        USING _source_work AS source ON target.camera_back_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            specifications = source.main_camera_specifications_json,
            features = source.main_camera_features,
            video = source.main_camera_video_json
        WHEN NOT MATCHED THEN INSERT
            (camera_back_id, specifications, features, video)
        VALUES (source.assigned_serial,
                source.main_camera_specifications_json,
                source.main_camera_features, source.main_camera_video_json)';

    EXECUTE 'MERGE INTO ' || s || '.camera_front AS target
        USING _source_work AS source ON target.camera_front_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            specifications = source.selfie_camera_specifications_json,
            features = source.selfie_camera_features,
            video = source.selfie_camera_video_json
        WHEN NOT MATCHED THEN INSERT
            (camera_front_id, specifications, features, video)
        VALUES (source.assigned_serial,
                source.selfie_camera_specifications_json,
                source.selfie_camera_features, source.selfie_camera_video_json)';

    EXECUTE 'MERGE INTO ' || s || '.features AS target
        USING _source_work AS source ON target.features_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            wlan = source.features_wlan,
            bluetooth = source.features_bluetooth,
            positioning = source.features_positioning,
            nfc = source.features_nfc,
            infrared_port = source.features_infrared_port,
            radio = source.features_radio,
            usb = source.features_usb,
            back_finger_print = source.features_back_finger_print,
            side_finger_print = source.features_side_finger_print,
            in_display_finger_print = source.features_in_display_finger_print,
            sensors = source.features_sensors
        WHEN NOT MATCHED THEN INSERT (
            features_id, wlan, bluetooth, positioning, nfc, infrared_port,
            radio, usb, back_finger_print, side_finger_print,
            in_display_finger_print, sensors
        ) VALUES (
            source.assigned_serial, source.features_wlan,
            source.features_bluetooth, source.features_positioning,
            source.features_nfc, source.features_infrared_port,
            source.features_radio, source.features_usb,
            source.features_back_finger_print,
            source.features_side_finger_print,
            source.features_in_display_finger_print, source.features_sensors
        )';

    EXECUTE 'MERGE INTO ' || s || '.battery AS target
        USING _source_work AS source ON target.battery_id = source.assigned_serial
        WHEN MATCHED THEN UPDATE SET
            capacity = source.battery_capacity,
            wireless_charging = source.battery_wireless_charging,
            charging = source.battery_charging_json
        WHEN NOT MATCHED THEN INSERT
            (battery_id, capacity, wireless_charging, charging)
        VALUES (source.assigned_serial, source.battery_capacity,
                source.battery_wireless_charging, source.battery_charging_json)';

    INSERT INTO warehouse.price_history (
        product_id, source_schema, source_serial_number, source_url,
        file_sha256, data_snapshot, data_snapshot_detail, amount, currency_code
    )
    SELECT
        w.product_id, p_source, w.assigned_serial, w.source_url,
        w.file_sha256, w.canonical_snapshot, w.canonical_snapshot_detail,
        price_value::DECIMAL(18,2), 'PKR'
    FROM _source_work w, w.prices_json price_value AT price_index
    WHERE price_value::DECIMAL(18,2) > 0
      AND NOT EXISTS (
          SELECT 1 FROM warehouse.price_history h
          WHERE h.source_schema = p_source
            AND h.source_url = w.source_url
            AND h.file_sha256 = w.file_sha256
            AND h.amount = price_value::DECIMAL(18,2)
      );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE PROCEDURE etl.load_all()
AS $$
DECLARE
    staged BIGINT;
    rejected BIGINT;
BEGIN
    SELECT COUNT(*) INTO staged FROM staging.phone_records;
    CALL etl.load_original();
    CALL etl.load_source('daraz');
    CALL etl.load_source('mymobile');
    CALL etl.load_source('mega');
    CALL etl.load_source('whatamobile');
    CALL etl.load_source('whatmobile');
    SELECT COUNT(*) INTO rejected
    FROM staging.phone_records r
    WHERE EXISTS (
        SELECT 1 FROM warehouse.etl_rejects e
        WHERE e.record_key = r.record_key
          AND e.reason_code IN (
              'INVALID_CANONICAL_SNAPSHOT',
              'NO_UNIQUE_GSMARENA_MATCH'
          )
          AND e.resolved_at IS NULL
    );
    INSERT INTO warehouse.load_runs (
        started_at, finished_at, staged_count, loaded_count,
        rejected_count, status
    ) VALUES (
        GETDATE(), GETDATE(), staged, staged - rejected, rejected,
        CASE WHEN rejected = 0 THEN 'completed' ELSE 'completed_with_rejects' END
    );
END;
$$ LANGUAGE plpgsql;

-- -------------------------------------------------------------------------
-- Read surfaces for BI.  These replace PostgreSQL table-returning functions;
-- Redshift and Power BI work best with stable views over set-based facts.
-- -------------------------------------------------------------------------

CREATE OR REPLACE VIEW warehouse.current_listings AS
SELECT
    'original'::VARCHAR(32) AS source_schema,
    o.serial_number AS source_serial_number,
    o.serial_number AS product_id,
    1::INTEGER AS instance_number,
    o.data_snapshot,
    o.data_snapshot_detail,
    o.name,
    o.url,
    o.price
FROM original.central_info o
UNION ALL
SELECT 'daraz', s.serial_number, c.product_id, c.instance_number,
       s.data_snapshot, s.data_snapshot_detail, s.name, s.url, s.price
FROM daraz.secondary_info s JOIN daraz.central_info c USING (serial_number)
UNION ALL
SELECT 'mymobile', s.serial_number, c.product_id, c.instance_number,
       s.data_snapshot, s.data_snapshot_detail, s.name, s.url, s.price
FROM mymobile.secondary_info s JOIN mymobile.central_info c USING (serial_number)
UNION ALL
SELECT 'mega', s.serial_number, c.product_id, c.instance_number,
       s.data_snapshot, s.data_snapshot_detail, s.name, s.url, s.price
FROM mega.secondary_info s JOIN mega.central_info c USING (serial_number)
UNION ALL
SELECT 'whatamobile', s.serial_number, c.product_id, c.instance_number,
       s.data_snapshot, s.data_snapshot_detail, s.name, s.url, s.price
FROM whatamobile.secondary_info s JOIN whatamobile.central_info c USING (serial_number)
UNION ALL
SELECT 'whatmobile', s.serial_number, c.product_id, c.instance_number,
       s.data_snapshot, s.data_snapshot_detail, s.name, s.url, s.price
FROM whatmobile.secondary_info s JOIN whatmobile.central_info c USING (serial_number);

CREATE OR REPLACE VIEW analytics.price_comparison AS
SELECT
    product_id,
    source_schema,
    source_serial_number,
    source_url,
    amount,
    currency_code,
    observed_at,
    data_snapshot,
    data_snapshot_detail
FROM warehouse.price_history
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY product_id, source_schema, source_url
    ORDER BY observed_at DESC, price_id DESC
) = 1;

CREATE OR REPLACE VIEW analytics.site_price_summary AS
SELECT
    source_schema,
    currency_code,
    COUNT(*) AS price_observations,
    COUNT(DISTINCT product_id) AS products,
    MIN(amount) AS minimum_price,
    AVG(amount) AS average_price,
    MAX(amount) AS maximum_price,
    MIN(observed_at) AS first_observed_at,
    MAX(observed_at) AS last_observed_at
FROM warehouse.price_history
WHERE amount > 0
GROUP BY source_schema, currency_code;

CREATE OR REPLACE VIEW analytics.incomplete_records AS
SELECT
    source_schema,
    source_url,
    source_file,
    completeness_score,
    loaded_at
FROM warehouse.raw_ingest
WHERE completeness_score < 0.80 OR completeness_score IS NULL;

CREATE OR REPLACE VIEW analytics.unmatched_records AS
SELECT
    record_key,
    source_schema,
    source_url,
    source_file,
    reason_code,
    reason_detail,
    rejected_at,
    resolved_at,
    resolution_detail
FROM warehouse.etl_rejects
WHERE reason_code = 'NO_UNIQUE_GSMARENA_MATCH'
  AND resolved_at IS NULL;

CREATE OR REPLACE VIEW analytics.product_bundle AS
SELECT
    c.serial_number AS product_id,
    c.data_snapshot,
    c.data_snapshot_detail,
    c.snapshot_source,
    c.name,
    c.url,
    c.colors,
    c.weight,
    c.price,
    n."2g", n."3g", n."4g", n."5g",
    l.announced, l.status,
    b.dimensions, b.weight AS body_weight, b.build, b.sim,
    b.protection AS body_protection,
    d.type AS display_type, d.size AS display_size,
    d.resolution AS display_resolution,
    d.protection AS display_protection,
    p.os, p.chipset, p.cpu, p.gpu,
    m.card_slot, m.technology AS memory_technology, m.types AS memory_types,
    cb.specifications AS main_camera_specifications,
    cb.features AS main_camera_features, cb.video AS main_camera_video,
    cf.specifications AS selfie_camera_specifications,
    cf.features AS selfie_camera_features, cf.video AS selfie_camera_video,
    f.wlan, f.bluetooth, f.positioning, f.nfc, f.infrared_port,
    f.radio, f.usb, f.back_finger_print, f.side_finger_print,
    f.in_display_finger_print, f.sensors,
    bat.capacity AS battery_capacity,
    bat.wireless_charging, bat.charging
FROM original.central_info c
LEFT JOIN original.network n ON n.network_id = c.network_id
LEFT JOIN original.launch l ON l.launch_id = c.launch_id
LEFT JOIN original.body b ON b.body_id = c.body_id
LEFT JOIN original.display d ON d.display_id = c.display_id
LEFT JOIN original.platform p ON p.platform_id = c.platform_id
LEFT JOIN original.memory m ON m.memory_id = c.memory_id
LEFT JOIN original.camera_back cb ON cb.camera_back_id = c.camera_back_id
LEFT JOIN original.camera_front cf ON cf.camera_front_id = c.camera_front_id
LEFT JOIN original.features f ON f.features_id = c.features_id
LEFT JOIN original.battery bat ON bat.battery_id = c.battery_id;
