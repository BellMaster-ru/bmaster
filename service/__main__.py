from service.cli import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Maintenance failed: {exc}")
        raise SystemExit(1)
