"""Console script for trace_poc."""
import os
from shutil import make_archive
import sys
import tempfile
import click
import requests


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--direct", is_flag=True)
def main(path, direct):
    """Console script for trace_poc."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        click.echo("PATH needs to be a directory")
        return 1
    if direct:
        click.echo(f"{path} will be passed directly")
    else:
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            make_archive(tmp.name[:-4], "zip", os.path.abspath(path))
            with requests.post(
                "http://127.0.0.1:8000",
                files={"file": ("random.zip", tmp)},
                headers=None,
                stream=True,
            ) as response:
                for line in response.iter_lines(decode_unicode=True):
                    print(line)
        click.echo(click.format_filename(os.path.abspath(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
