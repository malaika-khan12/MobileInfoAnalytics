-- MobileInfoAnalytics database functions v1
-- Target: PostgreSQL 15+ / Supabase.
-- Run db/schema_v1.sql before this file.

begin;

-- -------------------------------------------------------------------------
-- Safe JSON conversion helpers
-- -------------------------------------------------------------------------

create or replace function etl_private.json_text(p_value jsonb)
returns text
language sql
immutable
parallel safe
set search_path = pg_catalog
as $function$
    select case
        when p_value is null or p_value = 'null'::jsonb then null
        when jsonb_typeof(p_value) in ('string', 'number', 'boolean')
            then nullif(btrim(p_value #>> '{}'), '')
        else nullif(btrim(p_value::text), '')
    end
$function$;

create or replace function etl_private.json_text_array(p_value jsonb)
returns text[]
language sql
immutable
parallel safe
set search_path = pg_catalog, etl_private
as $function$
    with source_values as (
        select element, position
        from jsonb_array_elements(
            case
                when p_value is null or p_value = 'null'::jsonb
                    then '[]'::jsonb
                when jsonb_typeof(p_value) = 'array' then p_value
                else jsonb_build_array(p_value)
            end
        ) with ordinality as item(element, position)
    ), cleaned as (
        select etl_private.json_text(element) as value, position
        from source_values
    )
    select coalesce(
        array_agg(value order by position) filter (where value is not null),
        '{}'::text[]
    )
    from cleaned
$function$;

create or replace function etl_private.json_bool(
    p_value jsonb,
    p_default boolean
)
returns boolean
language plpgsql
immutable
parallel safe
set search_path = pg_catalog
as $function$
declare
    value_text text;
begin
    if p_value is null or p_value = 'null'::jsonb then
        return p_default;
    end if;

    if jsonb_typeof(p_value) = 'boolean' then
        return (p_value #>> '{}')::boolean;
    end if;

    value_text := lower(btrim(p_value #>> '{}'));
    if value_text in ('1', 'true', 't', 'yes', 'y', 'on', 'available', 'supported') then
        return true;
    end if;
    if value_text in ('0', 'false', 'f', 'no', 'n', 'off', 'none', 'unsupported') then
        return false;
    end if;
    return p_default;
end
$function$;

create or replace function etl_private.json_prices(p_value jsonb)
returns numeric(14,2)[]
language plpgsql
immutable
parallel safe
set search_path = pg_catalog
as $function$
declare
    container jsonb;
    element jsonb;
    value_text text;
    number_match text[];
    amount numeric(14,2);
    result numeric(14,2)[] := '{}'::numeric(14,2)[];
begin
    container := case
        when p_value is null or p_value = 'null'::jsonb then '[]'::jsonb
        when jsonb_typeof(p_value) = 'array' then p_value
        else jsonb_build_array(p_value)
    end;

    for element in select value from jsonb_array_elements(container)
    loop
        value_text := replace(coalesce(element #>> '{}', ''), ',', '');
        number_match := regexp_match(value_text, '[-+]?[0-9]+[.]?[0-9]*');
        if number_match is null then
            continue;
        end if;
        begin
            amount := number_match[1]::numeric(14,2);
            if amount > 0 then
                result := array_append(result, amount);
            end if;
        exception
            when invalid_text_representation or numeric_value_out_of_range then
                continue;
        end;
    end loop;

    if cardinality(result) = 0 then
        return array[-1.00]::numeric(14,2)[];
    end if;
    return result;
end
$function$;

create or replace function etl_private.normalize_name(p_name text)
returns text
language sql
immutable
parallel safe
set search_path = pg_catalog
as $function$
    select nullif(
        btrim(
            regexp_replace(
                lower(coalesce(p_name, '')),
                '[^a-z0-9]+',
                ' ',
                'g'
            )
        ),
        ''
    )
$function$;

create or replace function etl_private.json_has_value(p_value jsonb)
returns boolean
language sql
immutable
parallel safe
set search_path = pg_catalog
as $function$
    select case
        when p_value is null or p_value = 'null'::jsonb then false
        when jsonb_typeof(p_value) = 'string' then btrim(p_value #>> '{}') <> ''
        when jsonb_typeof(p_value) = 'array' then jsonb_array_length(p_value) > 0
        when jsonb_typeof(p_value) = 'object' then p_value <> '{}'::jsonb
        else true
    end
$function$;

create or replace function etl_private.json_completeness(p_payload jsonb)
returns numeric(6,5)
language sql
immutable
parallel safe
set search_path = pg_catalog, etl_private
as $function$
    with fields(value) as (
        values
            (p_payload -> 'MobileName'),
            (p_payload #> '{Launch,Announced}'),
            (p_payload #> '{Launch,Status}'),
            (p_payload #> '{Body,Dimensions}'),
            (p_payload #> '{Body,Weight}'),
            (p_payload #> '{Display,Type}'),
            (p_payload #> '{Display,Size}'),
            (p_payload #> '{Display,Resolution}'),
            (p_payload #> '{Platform,OS}'),
            (p_payload #> '{Platform,Chipset}'),
            (p_payload #> '{Platform,CPU}'),
            (p_payload #> '{Platform,GPU}'),
            (p_payload #> '{Memory,Types}'),
            (p_payload #> '{Main Camera,Specifications}'),
            (p_payload #> '{Selfie Camera,Specifications}'),
            (p_payload #> '{Features,WLAN}'),
            (p_payload #> '{Features,Bluetooth}'),
            (p_payload #> '{Features,USB}'),
            (p_payload #> '{Features,Sensors}'),
            (p_payload #> '{Battery,Capacity}'),
            (p_payload #> '{Battery,Charging}'),
            (p_payload -> 'Colors'),
            (p_payload -> 'Weight'),
            (p_payload -> 'Price')
    )
    select round(
        count(*) filter (where etl_private.json_has_value(value))::numeric
        / nullif(count(*), 0),
        5
    )::numeric(6,5)
    from fields
$function$;

-- -------------------------------------------------------------------------
-- Internal persistence helpers
-- -------------------------------------------------------------------------

create or replace function etl_private.assert_source_schema(p_schema text)
returns text
language plpgsql
immutable
parallel safe
set search_path = pg_catalog
as $function$
begin
    if p_schema not in ('daraz', 'mymobile', 'mega', 'whatamobile', 'whatmobile') then
        raise exception 'Unsupported source schema: %', p_schema
            using errcode = '22023';
    end if;
    return p_schema;
end
$function$;

create or replace function etl_private.record_raw_payload(
    p_source_schema text,
    p_source_url text,
    p_source_file text,
    p_snapshot timestamptz,
    p_payload jsonb
)
returns void
language sql
volatile
security definer
set search_path = pg_catalog
as $function$
    insert into warehouse.raw_ingest (
        source_schema, source_url, source_file, data_snapshot, payload
    )
    values (
        p_source_schema, p_source_url, p_source_file, p_snapshot, p_payload
    )
    on conflict (source_schema, source_url, data_snapshot, payload_md5)
    do nothing
$function$;

create or replace function etl_private.record_prices(
    p_source_schema text,
    p_source_serial_number bigint,
    p_product_id bigint,
    p_source_url text,
    p_product_name text,
    p_snapshot timestamptz,
    p_prices numeric(14,2)[]
)
returns void
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $function$
begin
    delete from warehouse.price_history
    where source_schema = p_source_schema
      and source_url = p_source_url
      and data_snapshot = p_snapshot;

    insert into warehouse.price_history (
        source_schema,
        source_serial_number,
        product_id,
        source_url,
        product_name,
        data_snapshot,
        price_position,
        amount,
        currency_code
    )
    select
        p_source_schema,
        p_source_serial_number,
        p_product_id,
        p_source_url,
        p_product_name,
        p_snapshot,
        price_position::smallint,
        amount,
        case when p_source_schema = 'original' then null else 'PKR' end
    from unnest(p_prices) with ordinality as price(amount, price_position)
    where amount > 0;
end
$function$;

create or replace function etl_private.upsert_detail_rows(
    p_schema text,
    p_network_id bigint,
    p_launch_id bigint,
    p_body_id bigint,
    p_display_id bigint,
    p_platform_id bigint,
    p_memory_id bigint,
    p_camera_back_id bigint,
    p_camera_front_id bigint,
    p_features_id bigint,
    p_battery_id bigint,
    p_payload jsonb
)
returns void
language plpgsql
volatile
security definer
set search_path = pg_catalog, etl_private
as $function$
begin
    if p_schema not in (
        'original', 'daraz', 'mymobile', 'mega', 'whatamobile', 'whatmobile'
    ) then
        raise exception 'Unsupported detail schema: %', p_schema
            using errcode = '22023';
    end if;

    execute format($sql$
        insert into %1$I.network (network_id, "2g", "3g", "4g", "5g")
        values ($1, $2, $3, $4, $5)
        on conflict (network_id) do update set
            "2g" = excluded."2g",
            "3g" = excluded."3g",
            "4g" = excluded."4g",
            "5g" = excluded."5g"
    $sql$, p_schema)
    using
        p_network_id,
        etl_private.json_bool(p_payload #> '{Network,2G}', true),
        etl_private.json_bool(p_payload #> '{Network,3G}', true),
        etl_private.json_bool(p_payload #> '{Network,4G}', false),
        etl_private.json_bool(p_payload #> '{Network,5G}', true);

    execute format($sql$
        insert into %1$I.launch (launch_id, announced, status)
        values ($1, $2, $3)
        on conflict (launch_id) do update set
            announced = excluded.announced,
            status = excluded.status
    $sql$, p_schema)
    using
        p_launch_id,
        etl_private.json_text(p_payload #> '{Launch,Announced}'),
        etl_private.json_text(p_payload #> '{Launch,Status}');

    execute format($sql$
        insert into %1$I.body
            (body_id, dimensions, weight, build, sim, protection)
        values ($1, $2, $3, $4, $5, $6)
        on conflict (body_id) do update set
            dimensions = excluded.dimensions,
            weight = excluded.weight,
            build = excluded.build,
            sim = excluded.sim,
            protection = excluded.protection
    $sql$, p_schema)
    using
        p_body_id,
        etl_private.json_text(p_payload #> '{Body,Dimensions}'),
        etl_private.json_text(p_payload #> '{Body,Weight}'),
        etl_private.json_text(p_payload #> '{Body,Build}'),
        etl_private.json_text(p_payload #> '{Body,SIM}'),
        etl_private.json_text(p_payload #> '{Body,Protection}');

    execute format($sql$
        insert into %1$I.display
            (display_id, type, size, resolution, protection)
        values ($1, $2, $3, $4, $5)
        on conflict (display_id) do update set
            type = excluded.type,
            size = excluded.size,
            resolution = excluded.resolution,
            protection = excluded.protection
    $sql$, p_schema)
    using
        p_display_id,
        etl_private.json_text(p_payload #> '{Display,Type}'),
        etl_private.json_text(p_payload #> '{Display,Size}'),
        etl_private.json_text(p_payload #> '{Display,Resolution}'),
        etl_private.json_text(p_payload #> '{Display,Protection}');

    execute format($sql$
        insert into %1$I.platform (platform_id, os, chipset, cpu, gpu)
        values ($1, $2, $3, $4, $5)
        on conflict (platform_id) do update set
            os = excluded.os,
            chipset = excluded.chipset,
            cpu = excluded.cpu,
            gpu = excluded.gpu
    $sql$, p_schema)
    using
        p_platform_id,
        etl_private.json_text(p_payload #> '{Platform,OS}'),
        etl_private.json_text(p_payload #> '{Platform,Chipset}'),
        etl_private.json_text(p_payload #> '{Platform,CPU}'),
        etl_private.json_text(p_payload #> '{Platform,GPU}');

    execute format($sql$
        insert into %1$I.memory (memory_id, card_slot, technology, types)
        values ($1, $2, $3, $4)
        on conflict (memory_id) do update set
            card_slot = excluded.card_slot,
            technology = excluded.technology,
            types = excluded.types
    $sql$, p_schema)
    using
        p_memory_id,
        etl_private.json_text(p_payload #> '{Memory,Card slot}'),
        etl_private.json_text(p_payload #> '{Memory,Technology}'),
        etl_private.json_text_array(p_payload #> '{Memory,Types}');

    execute format($sql$
        insert into %1$I.camera_back
            (camera_back_id, specifications, features, video)
        values ($1, $2, $3, $4)
        on conflict (camera_back_id) do update set
            specifications = excluded.specifications,
            features = excluded.features,
            video = excluded.video
    $sql$, p_schema)
    using
        p_camera_back_id,
        etl_private.json_text_array(
            p_payload #> '{Main Camera,Specifications}'
        ),
        etl_private.json_text(p_payload #> '{Main Camera,Features}'),
        etl_private.json_text_array(p_payload #> '{Main Camera,Video}');

    execute format($sql$
        insert into %1$I.camera_front
            (camera_front_id, specifications, features, video)
        values ($1, $2, $3, $4)
        on conflict (camera_front_id) do update set
            specifications = excluded.specifications,
            features = excluded.features,
            video = excluded.video
    $sql$, p_schema)
    using
        p_camera_front_id,
        etl_private.json_text_array(
            p_payload #> '{Selfie Camera,Specifications}'
        ),
        etl_private.json_text(p_payload #> '{Selfie Camera,Features}'),
        etl_private.json_text_array(p_payload #> '{Selfie Camera,Video}');

    execute format($sql$
        insert into %1$I.features (
            features_id, wlan, bluetooth, positioning, nfc,
            infrared_port, radio, usb, back_finger_print,
            side_finger_print, in_display_finger_print, sensors
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        on conflict (features_id) do update set
            wlan = excluded.wlan,
            bluetooth = excluded.bluetooth,
            positioning = excluded.positioning,
            nfc = excluded.nfc,
            infrared_port = excluded.infrared_port,
            radio = excluded.radio,
            usb = excluded.usb,
            back_finger_print = excluded.back_finger_print,
            side_finger_print = excluded.side_finger_print,
            in_display_finger_print = excluded.in_display_finger_print,
            sensors = excluded.sensors
    $sql$, p_schema)
    using
        p_features_id,
        etl_private.json_text(p_payload #> '{Features,WLAN}'),
        etl_private.json_text(p_payload #> '{Features,Bluetooth}'),
        etl_private.json_text(p_payload #> '{Features,Positioning}'),
        etl_private.json_bool(p_payload #> '{Features,NFC}', false),
        etl_private.json_bool(p_payload #> '{Features,Infrared port}', false),
        etl_private.json_bool(p_payload #> '{Features,Radio}', true),
        etl_private.json_text(p_payload #> '{Features,USB}'),
        etl_private.json_bool(p_payload #> '{Features,BackFingerPrint}', false),
        etl_private.json_bool(p_payload #> '{Features,SideFingerPrint}', false),
        etl_private.json_bool(
            p_payload #> '{Features,InDisplayFingerPrint}', false
        ),
        etl_private.json_text(p_payload #> '{Features,Sensors}');

    execute format($sql$
        insert into %1$I.battery
            (battery_id, capacity, wireless_charging, charging)
        values ($1, $2, $3, $4)
        on conflict (battery_id) do update set
            capacity = excluded.capacity,
            wireless_charging = excluded.wireless_charging,
            charging = excluded.charging
    $sql$, p_schema)
    using
        p_battery_id,
        etl_private.json_text(p_payload #> '{Battery,Capacity}'),
        etl_private.json_bool(
            p_payload #> '{Battery,WirelessCharging}', false
        ),
        etl_private.json_text_array(p_payload #> '{Battery,Charging}');
end
$function$;

create or replace function etl_private.link_listing(
    p_source_schema text,
    p_source_serial_number bigint,
    p_product_id bigint
)
returns integer
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $function$
declare
    existing_product_id bigint;
    existing_instance integer;
    next_instance integer;
    listing_exists boolean;
begin
    perform etl_private.assert_source_schema(p_source_schema);

    if not exists (
        select 1
        from original.central_info as product
        where product.serial_number = p_product_id
    ) then
        raise exception 'Canonical product % does not exist', p_product_id
            using errcode = '23503';
    end if;

    execute format(
        'select exists (select 1 from %I.secondary_info where serial_number = $1)',
        p_source_schema
    ) into listing_exists using p_source_serial_number;

    if not listing_exists then
        raise exception 'Source listing %.% does not exist',
            p_source_schema, p_source_serial_number
            using errcode = '23503';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended(p_source_schema || ':' || p_product_id::text, 0)
    );

    execute format(
        'select product_id, instance_number from %I.central_info where serial_number = $1',
        p_source_schema
    )
    into existing_product_id, existing_instance
    using p_source_serial_number;

    if existing_product_id = p_product_id then
        return existing_instance;
    end if;

    execute format(
        'select coalesce(max(instance_number), 0) + 1 from %I.central_info where product_id = $1',
        p_source_schema
    ) into next_instance using p_product_id;

    execute format($sql$
        insert into %1$I.central_info
            (serial_number, product_id, instance_number)
        values ($1, $2, $3)
        on conflict (serial_number) do update set
            product_id = excluded.product_id,
            instance_number = excluded.instance_number
    $sql$, p_source_schema)
    using p_source_serial_number, p_product_id, next_instance;

    update warehouse.price_history
    set product_id = p_product_id
    where source_schema = p_source_schema
      and source_serial_number = p_source_serial_number;

    return next_instance;
end
$function$;

-- -------------------------------------------------------------------------
-- Canonical and source upserts
-- -------------------------------------------------------------------------

create or replace function etl_private.upsert_original(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz,
    p_source_file text
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language plpgsql
volatile
security definer
set search_path = pg_catalog, etl_private
as $function$
declare
    product_name text;
    snapshot_at timestamptz := coalesce(p_snapshot, clock_timestamp());
    price_values numeric(14,2)[];
    color_values text[];
    source_id bigint;
    id_by_url bigint;
    id_by_name bigint;
    network_key bigint;
    launch_key bigint;
    body_key bigint;
    display_key bigint;
    platform_key bigint;
    memory_key bigint;
    camera_back_key bigint;
    camera_front_key bigint;
    features_key bigint;
    battery_key bigint;
begin
    if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
        raise exception 'payload must be a JSON object' using errcode = '22023';
    end if;
    product_name := etl_private.json_text(p_payload -> 'MobileName');
    if product_name is null then
        raise exception 'payload.MobileName is required' using errcode = '23502';
    end if;
    if p_source_url is null or p_source_url !~* '^https?://' then
        raise exception 'A valid HTTP(S) source URL is required' using errcode = '22023';
    end if;

    price_values := etl_private.json_prices(p_payload -> 'Price');
    color_values := etl_private.json_text_array(p_payload -> 'Colors');

    perform pg_advisory_xact_lock(
        hashtextextended('original:url:' || lower(p_source_url), 0)
    );
    perform pg_advisory_xact_lock(
        hashtextextended('original:name:' || etl_private.normalize_name(product_name), 0)
    );

    select item.serial_number into id_by_url
    from original.central_info as item
    where item.url = p_source_url;

    select item.serial_number into id_by_name
    from original.central_info as item
    where item.name = product_name;

    if id_by_url is not null and id_by_name is not null and id_by_url <> id_by_name then
        raise exception 'URL and MobileName identify different canonical products (% and %)',
            id_by_url, id_by_name using errcode = '23505';
    end if;

    source_id := coalesce(id_by_url, id_by_name);
    if source_id is null then
        insert into original.central_info as item (
            data_snapshot, name, url, sound_loudspeaker, sound_cable_jack,
            colors, weight, price
        )
        values (
            snapshot_at,
            product_name,
            p_source_url,
            etl_private.json_text(p_payload #> '{Sound,Loudspeaker}'),
            etl_private.json_bool(p_payload #> '{Sound,3.5mm jack}', true),
            color_values,
            coalesce(etl_private.json_text(p_payload -> 'Weight'), 'Weight Unknown'),
            price_values
        )
        returning
            item.serial_number, item.network_id, item.launch_id, item.body_id,
            item.display_id, item.platform_id, item.memory_id,
            item.camera_back_id, item.camera_front_id, item.features_id,
            item.battery_id
        into
            source_id, network_key, launch_key, body_key, display_key,
            platform_key, memory_key, camera_back_key, camera_front_key,
            features_key, battery_key;
        operation := 'inserted';
    else
        update original.central_info as item
        set data_snapshot = snapshot_at,
            name = product_name,
            url = p_source_url,
            sound_loudspeaker = etl_private.json_text(
                p_payload #> '{Sound,Loudspeaker}'
            ),
            sound_cable_jack = etl_private.json_bool(
                p_payload #> '{Sound,3.5mm jack}', true
            ),
            colors = color_values,
            weight = coalesce(
                etl_private.json_text(p_payload -> 'Weight'), 'Weight Unknown'
            ),
            price = price_values
        where item.serial_number = source_id
        returning
            item.network_id, item.launch_id, item.body_id, item.display_id,
            item.platform_id, item.memory_id, item.camera_back_id,
            item.camera_front_id, item.features_id, item.battery_id
        into
            network_key, launch_key, body_key, display_key, platform_key,
            memory_key, camera_back_key, camera_front_key, features_key,
            battery_key;
        operation := 'updated';
    end if;

    perform etl_private.upsert_detail_rows(
        'original', network_key, launch_key, body_key, display_key,
        platform_key, memory_key, camera_back_key, camera_front_key,
        features_key, battery_key, p_payload
    );
    perform etl_private.record_raw_payload(
        'original', p_source_url, p_source_file, snapshot_at, p_payload
    );
    perform etl_private.record_prices(
        'original', source_id, source_id, p_source_url, product_name,
        snapshot_at, price_values
    );

    source_serial_number := source_id;
    product_id := source_id;
    instance_number := 1;
    match_method := 'canonical';
    completeness_score := etl_private.json_completeness(p_payload);
    return next;
end
$function$;

create or replace function etl_private.upsert_source(
    p_source_schema text,
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz,
    p_source_file text,
    p_master_product_id bigint
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language plpgsql
volatile
security definer
set search_path = pg_catalog, etl_private
as $function$
declare
    source_schema text;
    product_name text;
    snapshot_at timestamptz := coalesce(p_snapshot, clock_timestamp());
    price_values numeric(14,2)[];
    color_values text[];
    source_id bigint;
    network_key bigint;
    launch_key bigint;
    body_key bigint;
    display_key bigint;
    platform_key bigint;
    memory_key bigint;
    camera_back_key bigint;
    camera_front_key bigint;
    features_key bigint;
    battery_key bigint;
    resolved_product_id bigint := p_master_product_id;
    normalized_source_name text;
    exact_match_count bigint;
    linked_instance integer;
begin
    source_schema := etl_private.assert_source_schema(p_source_schema);
    if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
        raise exception 'payload must be a JSON object' using errcode = '22023';
    end if;
    product_name := etl_private.json_text(p_payload -> 'MobileName');
    if product_name is null then
        raise exception 'payload.MobileName is required' using errcode = '23502';
    end if;
    if p_source_url is null or p_source_url !~* '^https?://' then
        raise exception 'A valid HTTP(S) source URL is required' using errcode = '22023';
    end if;

    price_values := etl_private.json_prices(p_payload -> 'Price');
    color_values := etl_private.json_text_array(p_payload -> 'Colors');
    normalized_source_name := etl_private.normalize_name(product_name);

    perform pg_advisory_xact_lock(
        hashtextextended(source_schema || ':url:' || lower(p_source_url), 0)
    );

    execute format($sql$
        select
            serial_number, network_id, launch_id, body_id, display_id,
            platform_id, memory_id, camera_back_id, camera_front_id,
            features_id, battery_id
        from %1$I.secondary_info
        where url = $1
    $sql$, source_schema)
    into
        source_id, network_key, launch_key, body_key, display_key,
        platform_key, memory_key, camera_back_key, camera_front_key,
        features_key, battery_key
    using p_source_url;

    if source_id is null then
        execute format($sql$
            insert into %1$I.secondary_info as item (
                data_snapshot, name, url, sound_loudspeaker,
                sound_cable_jack, colors, weight, price
            )
            values ($1, $2, $3, $4, $5, $6, $7, $8)
            returning
                item.serial_number, item.network_id, item.launch_id,
                item.body_id, item.display_id, item.platform_id,
                item.memory_id, item.camera_back_id, item.camera_front_id,
                item.features_id, item.battery_id
        $sql$, source_schema)
        into
            source_id, network_key, launch_key, body_key, display_key,
            platform_key, memory_key, camera_back_key, camera_front_key,
            features_key, battery_key
        using
            snapshot_at,
            product_name,
            p_source_url,
            etl_private.json_text(p_payload #> '{Sound,Loudspeaker}'),
            etl_private.json_bool(p_payload #> '{Sound,3.5mm jack}', true),
            color_values,
            coalesce(etl_private.json_text(p_payload -> 'Weight'), 'Weight Unknown'),
            price_values;
        operation := 'inserted';
    else
        execute format($sql$
            update %1$I.secondary_info
            set data_snapshot = $1,
                name = $2,
                sound_loudspeaker = $3,
                sound_cable_jack = $4,
                colors = $5,
                weight = $6,
                price = $7
            where serial_number = $8
        $sql$, source_schema)
        using
            snapshot_at,
            product_name,
            etl_private.json_text(p_payload #> '{Sound,Loudspeaker}'),
            etl_private.json_bool(p_payload #> '{Sound,3.5mm jack}', true),
            color_values,
            coalesce(etl_private.json_text(p_payload -> 'Weight'), 'Weight Unknown'),
            price_values,
            source_id;
        operation := 'updated';
    end if;

    perform etl_private.upsert_detail_rows(
        source_schema, network_key, launch_key, body_key, display_key,
        platform_key, memory_key, camera_back_key, camera_front_key,
        features_key, battery_key, p_payload
    );

    if resolved_product_id is null then
        select min(item.serial_number), count(*)
        into resolved_product_id, exact_match_count
        from original.central_info as item
        where etl_private.normalize_name(item.name) = normalized_source_name;

        if exact_match_count = 1 then
            match_method := 'exact_normalized_name';
        else
            resolved_product_id := null;
            match_method := 'unmatched';
        end if;
    else
        match_method := 'provided_product_id';
    end if;

    if resolved_product_id is not null then
        linked_instance := etl_private.link_listing(
            source_schema, source_id, resolved_product_id
        );
    end if;

    perform etl_private.record_raw_payload(
        source_schema, p_source_url, p_source_file, snapshot_at, p_payload
    );
    perform etl_private.record_prices(
        source_schema, source_id, resolved_product_id, p_source_url,
        product_name, snapshot_at, price_values
    );

    source_serial_number := source_id;
    product_id := resolved_product_id;
    instance_number := linked_instance;
    completeness_score := etl_private.json_completeness(p_payload);
    return next;
end
$function$;

-- -------------------------------------------------------------------------
-- Public ingestion RPCs.  They deliberately expose one named function per
-- source schema, as requested by functions_layout.txt, while sharing one
-- validated implementation internally.
-- -------------------------------------------------------------------------

create or replace function api.ingest_original(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql
volatile
security definer
set search_path = pg_catalog
as $function$
    select *
    from etl_private.upsert_original(
        p_payload, p_source_url, p_snapshot, p_source_file
    )
$function$;

create or replace function api.ingest_daraz(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null,
    p_master_product_id bigint default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql volatile security definer set search_path = pg_catalog
as $function$
    select * from etl_private.upsert_source(
        'daraz', p_payload, p_source_url, p_snapshot,
        p_source_file, p_master_product_id
    )
$function$;

create or replace function api.ingest_mymobile(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null,
    p_master_product_id bigint default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql volatile security definer set search_path = pg_catalog
as $function$
    select * from etl_private.upsert_source(
        'mymobile', p_payload, p_source_url, p_snapshot,
        p_source_file, p_master_product_id
    )
$function$;

create or replace function api.ingest_mega(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null,
    p_master_product_id bigint default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql volatile security definer set search_path = pg_catalog
as $function$
    select * from etl_private.upsert_source(
        'mega', p_payload, p_source_url, p_snapshot,
        p_source_file, p_master_product_id
    )
$function$;

create or replace function api.ingest_whatamobile(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null,
    p_master_product_id bigint default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql volatile security definer set search_path = pg_catalog
as $function$
    select * from etl_private.upsert_source(
        'whatamobile', p_payload, p_source_url, p_snapshot,
        p_source_file, p_master_product_id
    )
$function$;

create or replace function api.ingest_whatmobile(
    p_payload jsonb,
    p_source_url text,
    p_snapshot timestamptz default clock_timestamp(),
    p_source_file text default null,
    p_master_product_id bigint default null
)
returns table (
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    operation text,
    match_method text,
    completeness_score numeric(6,5)
)
language sql volatile security definer set search_path = pg_catalog
as $function$
    select * from etl_private.upsert_source(
        'whatmobile', p_payload, p_source_url, p_snapshot,
        p_source_file, p_master_product_id
    )
$function$;

-- -------------------------------------------------------------------------
-- Product matching and ETL run maintenance
-- -------------------------------------------------------------------------

create or replace function api.link_source_product(
    p_source_schema text,
    p_source_serial_number bigint,
    p_product_id bigint
)
returns table (product_id bigint, instance_number integer)
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $function$
begin
    product_id := p_product_id;
    instance_number := etl_private.link_listing(
        p_source_schema, p_source_serial_number, p_product_id
    );
    return next;
end
$function$;

create or replace function api.refresh_exact_name_links(
    p_source_schema text default null
)
returns bigint
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $function$
declare
    listing record;
    matched_product bigint;
    match_count bigint;
    linked_count bigint := 0;
begin
    if p_source_schema is not null then
        perform etl_private.assert_source_schema(p_source_schema);
    end if;

    for listing in
        select current_listing.source_schema,
               current_listing.source_serial_number,
               current_listing.name
        from warehouse.current_listings as current_listing
        where current_listing.source_schema <> 'original'
          and current_listing.product_id is null
          and (
              p_source_schema is null
              or current_listing.source_schema = p_source_schema
          )
    loop
        select min(product.serial_number), count(*)
        into matched_product, match_count
        from original.central_info as product
        where etl_private.normalize_name(product.name)
            = etl_private.normalize_name(listing.name);

        if match_count = 1 then
            perform etl_private.link_listing(
                listing.source_schema,
                listing.source_serial_number,
                matched_product
            );
            linked_count := linked_count + 1;
        end if;
    end loop;
    return linked_count;
end
$function$;

create or replace function api.start_ingest_run(
    p_target_kind text,
    p_source_manifest text,
    p_details jsonb default '{}'::jsonb
)
returns bigint
language sql
volatile
security definer
set search_path = pg_catalog
as $function$
    insert into warehouse.ingest_runs (
        target_kind, source_manifest, details
    ) values (
        coalesce(nullif(btrim(p_target_kind), ''), 'supabase'),
        p_source_manifest,
        coalesce(p_details, '{}'::jsonb)
    )
    returning run_id
$function$;

create or replace function api.finish_ingest_run(
    p_run_id bigint,
    p_rows_attempted bigint,
    p_rows_succeeded bigint,
    p_rows_failed bigint,
    p_status text,
    p_details jsonb default '{}'::jsonb
)
returns void
language plpgsql
volatile
security definer
set search_path = pg_catalog
as $function$
begin
    if p_status not in ('completed', 'completed_with_errors', 'failed') then
        raise exception 'Invalid final ingest status: %', p_status
            using errcode = '22023';
    end if;

    update warehouse.ingest_runs
    set finished_at = clock_timestamp(),
        rows_attempted = greatest(coalesce(p_rows_attempted, 0), 0),
        rows_succeeded = greatest(coalesce(p_rows_succeeded, 0), 0),
        rows_failed = greatest(coalesce(p_rows_failed, 0), 0),
        status = p_status,
        details = details || coalesce(p_details, '{}'::jsonb)
    where run_id = p_run_id;

    if not found then
        raise exception 'Ingest run % does not exist', p_run_id
            using errcode = 'P0002';
    end if;
end
$function$;

create or replace function api.log_ingest_reject(
    p_run_id bigint,
    p_source_schema text,
    p_source_file text,
    p_source_url text,
    p_error_code text,
    p_error_message text,
    p_payload jsonb default null
)
returns bigint
language sql
volatile
security definer
set search_path = pg_catalog
as $function$
    insert into warehouse.etl_rejects (
        run_id, source_schema, source_file, source_url,
        error_code, error_message, payload
    ) values (
        p_run_id, p_source_schema, p_source_file, p_source_url,
        coalesce(nullif(btrim(p_error_code), ''), 'LOAD_ERROR'),
        coalesce(nullif(btrim(p_error_message), ''), 'Unknown load error'),
        p_payload
    )
    returning reject_id
$function$;

-- -------------------------------------------------------------------------
-- Analytics and completeness functions
-- -------------------------------------------------------------------------

create or replace function api.unmatched_listings(
    p_source_schema text default null
)
returns table (
    source_schema text,
    source_serial_number bigint,
    data_snapshot timestamptz,
    name text,
    url text,
    prices numeric(14,2)[]
)
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    select
        listing.source_schema,
        listing.source_serial_number,
        listing.data_snapshot,
        listing.name,
        listing.url,
        listing.price
    from warehouse.current_listings as listing
    where listing.source_schema <> 'original'
      and listing.product_id is null
      and (p_source_schema is null or listing.source_schema = p_source_schema)
    order by listing.source_schema, listing.name, listing.source_serial_number
$function$;

create or replace function api.complete_listings(
    p_minimum_completeness numeric default 0.65,
    p_matched_only boolean default false,
    p_source_schema text default null
)
returns table (
    source_schema text,
    source_serial_number bigint,
    product_id bigint,
    instance_number integer,
    data_snapshot timestamptz,
    name text,
    url text,
    prices numeric(14,2)[],
    completeness_score numeric(6,5),
    payload jsonb
)
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    select
        listing.source_schema,
        listing.source_serial_number,
        listing.product_id,
        listing.instance_number,
        listing.data_snapshot,
        listing.name,
        listing.url,
        listing.price,
        etl_private.json_completeness(raw_record.payload),
        raw_record.payload
    from warehouse.current_listings as listing
    join lateral (
        select raw.payload
        from warehouse.raw_ingest as raw
        where raw.source_schema = listing.source_schema
          and raw.source_url = listing.url
        order by raw.data_snapshot desc, raw.raw_id desc
        limit 1
    ) as raw_record on true
    where etl_private.json_completeness(raw_record.payload)
            >= greatest(least(coalesce(p_minimum_completeness, 0.65), 1), 0)
      and (not p_matched_only or listing.product_id is not null)
      and (p_source_schema is null or listing.source_schema = p_source_schema)
    order by listing.product_id nulls last,
             listing.source_schema,
             listing.instance_number nulls last
$function$;

create or replace function api.price_comparison(p_product_id bigint)
returns table (
    source_schema text,
    source_serial_number bigint,
    instance_number integer,
    product_name text,
    source_url text,
    data_snapshot timestamptz,
    current_price numeric(14,2),
    cheapest_price numeric(14,2),
    difference_from_cheapest numeric(14,2),
    percent_above_cheapest numeric(12,4),
    is_cheapest boolean
)
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    with listing_prices as (
        select
            price.source_schema,
            price.source_serial_number,
            price.instance_number,
            price.name,
            price.url,
            price.data_snapshot,
            min(price.amount)::numeric(14,2) as current_price
        from warehouse.current_prices as price
        where price.product_id = p_product_id
          and price.currency_code = 'PKR'
        group by
            price.source_schema,
            price.source_serial_number,
            price.instance_number,
            price.name,
            price.url,
            price.data_snapshot
    ), compared as (
        select listing_prices.*,
               min(listing_prices.current_price) over () as cheapest_price
        from listing_prices
    )
    select
        compared.source_schema,
        compared.source_serial_number,
        compared.instance_number,
        compared.name,
        compared.url,
        compared.data_snapshot,
        compared.current_price,
        compared.cheapest_price,
        (compared.current_price - compared.cheapest_price)::numeric(14,2),
        round(
            100 * (compared.current_price - compared.cheapest_price)
            / nullif(compared.cheapest_price, 0),
            4
        )::numeric(12,4),
        compared.current_price = compared.cheapest_price
    from compared
    order by compared.current_price, compared.source_schema, compared.instance_number
$function$;

create or replace function api.product_price_history(
    p_product_id bigint,
    p_from timestamptz default '-infinity'::timestamptz,
    p_to timestamptz default 'infinity'::timestamptz
)
returns table (
    source_schema text,
    source_serial_number bigint,
    source_url text,
    product_name text,
    data_snapshot timestamptz,
    price_position smallint,
    amount numeric(14,2),
    currency_code text
)
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    select
        history.source_schema,
        history.source_serial_number,
        history.source_url,
        history.product_name,
        history.data_snapshot,
        history.price_position,
        history.amount,
        history.currency_code
    from warehouse.price_history as history
    where history.product_id = p_product_id
      and history.data_snapshot >= coalesce(p_from, '-infinity'::timestamptz)
      and history.data_snapshot <= coalesce(p_to, 'infinity'::timestamptz)
    order by history.data_snapshot, history.source_schema, history.price_position
$function$;

create or replace function api.site_price_summary(
    p_from timestamptz default '-infinity'::timestamptz,
    p_to timestamptz default 'infinity'::timestamptz
)
returns table (
    source_schema text,
    listing_count bigint,
    product_count bigint,
    observation_count bigint,
    minimum_price numeric(14,2),
    average_price numeric(14,2),
    maximum_price numeric(14,2)
)
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    with observation as (
        select distinct on (
            history.source_schema,
            history.source_url,
            history.data_snapshot
        )
            history.source_schema,
            history.source_serial_number,
            history.product_id,
            history.data_snapshot,
            history.amount
        from warehouse.price_history as history
        where history.currency_code = 'PKR'
          and history.data_snapshot >= coalesce(p_from, '-infinity'::timestamptz)
          and history.data_snapshot <= coalesce(p_to, 'infinity'::timestamptz)
        order by
            history.source_schema,
            history.source_url,
            history.data_snapshot,
            history.amount
    )
    select
        observation.source_schema,
        count(distinct observation.source_serial_number),
        count(distinct observation.product_id),
        count(*),
        min(observation.amount)::numeric(14,2),
        round(avg(observation.amount), 2)::numeric(14,2),
        max(observation.amount)::numeric(14,2)
    from observation
    group by observation.source_schema
    order by observation.source_schema
$function$;

create or replace function api.product_bundle(p_product_id bigint)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog
as $function$
    select case
        when canonical.serial_number is null then null
        else jsonb_build_object(
            'product_id', canonical.serial_number,
            'name', canonical.name,
            'url', canonical.url,
            'data_snapshot', canonical.data_snapshot,
            'canonical_payload', canonical_raw.payload,
            'listings', coalesce(listing_records.records, '[]'::jsonb)
        )
    end
    from original.central_info as canonical
    left join lateral (
        select raw.payload
        from warehouse.raw_ingest as raw
        where raw.source_schema = 'original'
          and raw.source_url = canonical.url
        order by raw.data_snapshot desc, raw.raw_id desc
        limit 1
    ) as canonical_raw on true
    left join lateral (
        select jsonb_agg(
            jsonb_build_object(
                'source_schema', listing.source_schema,
                'source_serial_number', listing.source_serial_number,
                'instance_number', listing.instance_number,
                'name', listing.name,
                'url', listing.url,
                'data_snapshot', listing.data_snapshot,
                'prices', listing.price,
                'payload', latest_raw.payload
            )
            order by listing.source_schema, listing.instance_number
        ) as records
        from warehouse.current_listings as listing
        left join lateral (
            select raw.payload
            from warehouse.raw_ingest as raw
            where raw.source_schema = listing.source_schema
              and raw.source_url = listing.url
            order by raw.data_snapshot desc, raw.raw_id desc
            limit 1
        ) as latest_raw on true
        where listing.product_id = canonical.serial_number
          and listing.source_schema <> 'original'
    ) as listing_records on true
    where canonical.serial_number = p_product_id
$function$;

comment on function api.ingest_original(jsonb, text, timestamptz, text) is
    'Idempotently upserts one GSMArena template payload and records raw/history rows.';
comment on function api.price_comparison(bigint) is
    'Compares the minimum current positive PKR price for every matched marketplace listing.';
comment on function api.complete_listings(numeric, boolean, text) is
    'Returns only listings whose latest raw payload reaches the requested completeness ratio.';

-- No direct execution is available to PUBLIC, anon, or authenticated.  The
-- service role receives the narrow API schema only; etl_private stays hidden.
revoke all on all functions in schema etl_private from public;
revoke all on all functions in schema api from public;

do $security$
declare
    role_name text;
begin
    foreach role_name in array array['anon', 'authenticated']
    loop
        if exists (select 1 from pg_roles where rolname = role_name) then
            execute format('revoke all on all functions in schema api from %I', role_name);
            execute format(
                'revoke all on all functions in schema etl_private from %I', role_name
            );
        end if;
    end loop;

    if exists (select 1 from pg_roles where rolname = 'service_role') then
        grant usage on schema api to service_role;
        grant execute on all functions in schema api to service_role;
    end if;
end
$security$;

commit;
