"""Repository wrapper for UNITI's packaged alpha smoke workflow."""

from uniti.app.smoke import main, run_alpha_smoke

DOGFOOD_SMOKE_FIELDS = (
    "dogfood_single_owner",
    "dogfood_remained_active",
    "dogfood_published",
    "dogfood_retention_days",
    "dogfood_aggregate_max_mib",
)

__all__ = ["DOGFOOD_SMOKE_FIELDS", "main", "run_alpha_smoke"]


if __name__ == "__main__":
    raise SystemExit(main())
