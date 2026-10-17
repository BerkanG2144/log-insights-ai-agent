CREATE TABLE bgl_logs (
    line_no BIGINT PRIMARY KEY,
    raw_line VARCHAR NOT NULL,
    ts TIMESTAMP,
    component VARCHAR,
    level VARCHAR,
    message VARCHAR,
    parse_status VARCHAR NOT NULL,
    ts_unix BIGINT,
    node VARCHAR,
    rack VARCHAR,
    label VARCHAR,
    is_alert BOOLEAN
);

CREATE TABLE openstack_logs (
    line_no BIGINT NOT NULL,
    raw_line VARCHAR NOT NULL,
    ts TIMESTAMP,
    component VARCHAR,
    level VARCHAR,
    message VARCHAR,
    parse_status VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    pid INTEGER,
    service VARCHAR,
    request_id VARCHAR,
    instance_id VARCHAR,
    http_status INTEGER,
    latency_s DOUBLE PRECISION,
    PRIMARY KEY (source_file, line_no)
);

CREATE TABLE openstack_anomaly_vms (
    instance_id VARCHAR PRIMARY KEY
);

CREATE TABLE team_ownership (
    dataset VARCHAR NOT NULL,
    component VARCHAR NOT NULL,
    team VARCHAR NOT NULL,
    PRIMARY KEY (dataset, component)
);
