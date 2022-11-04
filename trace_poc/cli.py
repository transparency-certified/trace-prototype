"""Console script for trace_poc."""
import os
from shutil import make_archive
import sys
import tempfile
import zipfile

import click
import requests


@click.group()
@click.option("--debug/--no-debug", default=False)
def main(debug):
    """Define main command group."""
    if debug:
        click.echo("Debug mode is 'on'")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--direct",
    help="Pass PATH directly instead of creating a zipball out of it.",
    is_flag=True,
)
@click.option(
    "--entrypoint",
    help="Entrypoint that should be used while executing a run.",
    type=str,
    show_default=True,
    default="run.sh",
)
def submit(path, direct, entrypoint):
    """Submit a job to a TRACE system."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        click.echo("PATH needs to be a directory")
        return 1
    if direct:
        click.echo(f"{path} will be passed directly")
        with requests.post(
            "http://127.0.0.1:8000",
            params={"entrypoint": entrypoint, "path": path},
            stream=True,
        ) as response:
            for line in response.iter_lines(decode_unicode=True):
                print(line)
    else:
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            make_archive(tmp.name[:-4], "zip", os.path.abspath(path))
            with requests.post(
                "http://127.0.0.1:8000",
                params={"entrypoint": entrypoint},
                files={"file": ("random.zip", tmp)},
                stream=True,
            ) as response:
                for line in response.iter_lines(decode_unicode=True):
                    print(line)
        click.echo(click.format_filename(os.path.abspath(path)))
    return 0


@main.command()
@click.argument("path", type=str)
def download(path):
    """Download an exisiting zipball with a run."""
    with requests.get(f"http://127.0.0.1:8000/run/{path}", stream=True) as response:
        response.raise_for_status()
        with open(os.path.join("/tmp", path), "wb") as fp:
            for chunk in response.iter_content(chunk_size=8192):
                fp.write(chunk)
    click.echo(f"Run downloaded as /tmp/{path}")


@main.command()
@click.argument("path", type=click.Path(exists=True))
def verify(path):
    """Verify that a run is valid and signed."""
    with requests.post(
        "http://127.0.0.1:8000/verify",
        files={"file": (os.path.basename(path), open(path, "rb"))},
        stream=True,
    ) as response:
        try:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                print(line)
        except requests.exceptions.HTTPError as exc:
            print(exc, response.text)


@main.command()
@click.argument("path", type=click.Path(exists=True))
def inspect(path):
    """Inspect TRO (if any) of a run."""
    with zipfile.ZipFile(path, "r") as zf:
        metadata = zf.read("bag-info.txt")
    print(f"\U0001F50D Inspecting {path}")
    for line in metadata.decode().strip().split("\n"):
        key, value = line.split(":", 1)
        if key in ("Bag-Software-Agent", "BagIt-Profile-Identifier", "Payload-Oxum"):
            continue
        print(f"\t \U00002B50 {key} - {value.strip()}")


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
