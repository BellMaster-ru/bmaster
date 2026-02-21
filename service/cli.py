import argparse
from typing import Optional

from service.operations import bootstrap, print_check_result, print_update_result


def _handle_bootstrap(args: argparse.Namespace) -> int:
    return bootstrap(update_cert=args.update_cert)


def _handle_check(_: argparse.Namespace) -> int:
    print_check_result()
    return 0


def _handle_update(_: argparse.Namespace) -> int:
    print_update_result()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="bmaster install/update maintenance utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Initialize data, cert and frontend")
    bootstrap_parser.add_argument(
        "--update-cert",
        action="store_true",
        help="Force regenerate SSL certificate even if it already exists",
    )
    bootstrap_parser.set_defaults(handler=_handle_bootstrap)

    check_parser = subparsers.add_parser("check", help="Check backend and frontend updates")
    check_parser.set_defaults(handler=_handle_check)

    update_parser = subparsers.add_parser("update", help="Update backend and frontend")
    update_parser.set_defaults(handler=_handle_update)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
