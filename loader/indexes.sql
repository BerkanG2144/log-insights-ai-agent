-- Syntax verified against SereneDB 26.10.1's built-in sdb_docs.search.
-- Search the index by its name. Base tables remain available for analytics.
CREATE TEXT SEARCH DICTIONARY log_insights_words AS
    split_text(case := 'lower') WITH (frequency, position);

CREATE INDEX bgl_logs_message_idx ON bgl_logs USING inverted (
    line_no, ts, component, level, node, rack, label, is_alert,
    message log_insights_words
) INCLUDE (raw_line, ts_unix, parse_status);

CREATE INDEX openstack_logs_message_idx ON openstack_logs USING inverted (
    source_file, line_no, ts, component, level, service, request_id, instance_id,
    http_status, message log_insights_words
) INCLUDE (raw_line, pid, latency_s, parse_status);
