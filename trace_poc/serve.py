"""Console script for trace_poc."""
import sys
import click
from waitress import serve


@click.command()
def main(args=None):
    """Console script for trace_poc."""
    from trace_poc.server import app
    serve(app, host="0.0.0.0", port=8000)
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
