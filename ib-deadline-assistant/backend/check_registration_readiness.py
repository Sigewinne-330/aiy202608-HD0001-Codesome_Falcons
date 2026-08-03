"""CLI entry point for registration email-verification readiness checks."""

from services.registration_readiness import main


if __name__ == "__main__":
    raise SystemExit(main())
