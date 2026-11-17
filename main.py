from argparse import ArgumentParser
from cli.api_rate_limit_cli import APIRateLimitCLI


def main():
    parser = ArgumentParser(description="API Rate-Limit & Circuit-Breaker Resilience Engine")
    parser.add_argument(
        "--api-endpoints",
        nargs="+",
        required=True,
        help="List of API endpoints to audit",
    )
    args = parser.parse_args()
    cli = APIRateLimitCLI(args.api_endpoints)
    cli.run()


if __name__ == "__main__":
    main()
