"""Legacy config migration helpers."""


def migrate_config(config):
    migrated = dict(config)
    migrated["version"] = 2

    if "timeout_ms" in migrated:
        migrated["timeout_seconds"] = migrated["timeout_ms"] // 1000
    if "max_retries" in migrated:
        migrated["retries"] = migrated["max_retries"]
    if "enable_cache" in migrated:
        migrated["cache_enabled"] = migrated["enable_cache"]

    return migrated
