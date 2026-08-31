"""Repository wrapper for UNITI's packaged alpha smoke workflow."""

from uniti.app.smoke import main, run_alpha_smoke

__all__ = ["main", "run_alpha_smoke"]


if __name__ == "__main__":
    raise SystemExit(main())
