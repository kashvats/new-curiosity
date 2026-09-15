"""Manual HA coordination smoke test for sqlite/redis/postgres backends.

Run with the same scheduler environment variables as the backend. It only
acquires/releases coordination leases; it never creates improvement cycles.
"""
from app.improvement_scheduler_ha import acquire_scheduler_lease, release_scheduler_lease, validate_scheduler_lease


def main() -> None:
    key = "scheduler:part11-ha-smoke"
    first = acquire_scheduler_lease(key, owner_id="smoke-a", ttl_seconds=15)
    assert first.get("acquired"), first
    token1 = int(first["fence_token"])
    assert validate_scheduler_lease(key, owner_id="smoke-a", fence_token=token1)
    assert release_scheduler_lease(key, owner_id="smoke-a", fence_token=token1)

    second = acquire_scheduler_lease(key, owner_id="smoke-b", ttl_seconds=15)
    assert second.get("acquired"), second
    token2 = int(second["fence_token"])
    assert token2 > token1, (token1, token2)
    assert not validate_scheduler_lease(key, owner_id="smoke-a", fence_token=token1)
    assert validate_scheduler_lease(key, owner_id="smoke-b", fence_token=token2)
    assert release_scheduler_lease(key, owner_id="smoke-b", fence_token=token2)
    print(f"HA failover smoke passed: fence {token1} -> {token2}")


if __name__ == "__main__":
    main()
