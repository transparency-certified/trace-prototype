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
@click.option(
    "--container-user",
    help="User that will execute shell inside the container.",
    type=str,
    show_default=True,
    default="jovyan",
)
@click.option(
    "--target-repo-dir",
    help="Path to the working directory inside the container.",
    type=str,
    show_default=True,
    default="/home/jovyan/work",
)
@click.option(
    "--trace-server",
    help="TRACE server to submit the job to.",
    type=str,
    show_default=True,
    default="http://127.0.0.1:8000",
)
@click.option(
    "--enable-network",
    help="Disable network isolation for the run.",
    is_flag=True,
    default=False,
    show_default=True,
)
def submit(
    path,
    direct,
    entrypoint,
    container_user,
    target_repo_dir,
    trace_server,
    enable_network,
):
    """Submit a job to a TRACE system."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        click.echo("PATH needs to be a directory")
        return 1
    if direct:
        click.echo(f"{path} will be passed directly")
        with requests.post(
            trace_server,
            params={
                "entrypoint": entrypoint,
                "path": path,
                "containerUser": container_user,
                "targetRepoDir": target_repo_dir,
                "networkEnabled": enable_network,
            },
            stream=True,
        ) as response:
            for line in response.iter_lines(decode_unicode=True):
                print(line)
    else:
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            make_archive(tmp.name[:-4], "zip", os.path.abspath(path))
            with requests.post(
                trace_server,
                params={
                    "entrypoint": entrypoint,
                    "containerUser": container_user,
                    "targetRepoDir": target_repo_dir,
                    "networkEnabled": enable_network,
                },
                files={"file": ("random.zip", tmp)},
                stream=True,
            ) as response:
                for line in response.iter_lines(decode_unicode=True):
                    print(line)
        click.echo(click.format_filename(os.path.abspath(path)))
    return 0


@main.command()
@click.argument("path", type=str)
@click.option(
    "--trace-server",
    help="TRACE server to submit the job to.",
    type=str,
    show_default=True,
    default="http://127.0.0.1:8000",
)
def download(path, trace_server):
    """Download an exisiting zipball with a run."""
    tmpdir = tempfile.mkdtemp()
    for ext in (".sig", ".jsonld", "_run.zip", ".tsr"):
        with requests.get(f"{trace_server}/run/{path}{ext}", stream=True) as response:
            response.raise_for_status()
            with open(os.path.join(tmpdir, f"{path}{ext}"), "wb") as fp:
                for chunk in response.iter_content(chunk_size=8192):
                    fp.write(chunk)
    click.echo(f"Run downloaded to {tmpdir}")


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--trace-server",
    help="TRACE server to submit the job to.",
    type=str,
    show_default=True,
    default="http://127.0.0.1:8000",
)
def verify(path, trace_server):
    """Verify that a run is valid and signed."""
    with requests.post(
        f"{trace_server}/verify",
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
