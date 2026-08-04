"""CLI entry point for reminder runtime readiness checks."""

from services.reminder_readiness import main


if __name__ == "__main__":
    raise SystemExit(main())
