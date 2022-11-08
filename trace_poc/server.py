"""Main TRACE PoC API layer."""
import hashlib
import json
import os
import random
import re
import shutil
import signal
import string
import subprocess
import uuid
import tempfile
import zipfile
import gnupg

import bagit
from bdbag import bdbag_api as bdb
import docker
from flask import Flask, stream_with_context, request, send_from_directory

app = Flask(__name__)
TMP_PATH = os.path.join(os.environ.get("HOSTDIR", "/"), "tmp")
CERTS_PATH = os.environ.get("TRACE_CERTS_PATH", os.path.abspath("../volumes/certs"))
GPG_HOME = os.environ.get("GPG_HOME", "/etc/gpg")
GPG_FINGERPRINT = os.environ.get("GPG_FINGERPRINT")
GPG_PASSPHRASE = os.environ.get("GPG_PASSPHRASE")
STORAGE_PATH = os.environ.get(
    "TRACE_STORAGE_PATH", os.path.abspath("../volumes/storage")
)
TRACE_CLAIMS_FILE = os.path.join(CERTS_PATH, "claims.json")
if not os.path.isfile(TRACE_CLAIMS_FILE):
    TRACE_CLAIMS = {
        "Platform": "My awesome platform!",
        "ProvidedBy": "Xarthisius",
        "Features": "Ran your code with care and love (even though I would write it better...)",
    }
else:
    TRACE_CLAIMS = json.load(open(TRACE_CLAIMS_FILE, "r"))

try:
    gpg = gnupg.GPG(gnupghome=GPG_HOME)
    GPG_KEYID = gpg.list_keys().key_map[GPG_FINGERPRINT]["keyid"]
except KeyError:
    raise RuntimeError("Configured GPG_FINGERPRINT not found.")


def build_image(payload_zip, temp_dir, image):
    """Part of the workflow resposible for building image."""
    yield "\U0001F64F Start building\n"
    # For WT specific buildpacks we would need to inject env.json
    # with open(os.path.join(temp_dir, "environment.json")) as fp:
    #     json.dump({"config": {"buildpack": "PythonBuildPack"}}, fp)
    shutil.unpack_archive(payload_zip, temp_dir, "zip")
    _set_workdir_ownership(temp_dir)
    op = "--no-run"
    letters = string.ascii_lowercase
    image["tag"] = f"local/{''.join(random.choice(letters) for i in range(8))}"
    r2d_cmd = (
        f"jupyter-repo2docker --engine dockercli "
        "--config='/wholetale/repo2docker_config.py' "
        f"--target-repo-dir='{image['target_repo_dir']}' "
        f"--user-id=1000 --user-name={image['container_user']} "
        f"--no-clean {op} --debug {image['extra_args']} "
        f"--image-name {image['tag']} {temp_dir}"
    )
    volumes = {
        "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
        "/tmp": {"bind": TMP_PATH, "mode": "ro"},
    }

    cli = docker.from_env()
    container = cli.containers.run(
        image="wholetale/repo2docker_wholetale:latest",
        command=r2d_cmd,
        environment=["DOCKER_HOST=unix:///var/run/docker.sock"],
        privileged=True,
        detach=True,
        remove=True,
        volumes=volumes,
        working_dir=image["target_repo_dir"],
    )
    for line in container.logs(stream=True):
        yield line.decode("utf-8")
    ret = container.wait()
    if ret["StatusCode"] != 0:
        raise RuntimeError("Error building image")
    yield "\U0001F64C Finished building\n"


def run(temp_dir, image):
    """Part of the workflow running recorded run."""
    yield "\U0001F44A Start running\n"
    cli = docker.from_env()
    container = cli.containers.create(
        image=image["tag"],
        command=f"sh {image['entrypoint']}",
        detach=True,
        network_disabled=True,
        user=image["container_user"],
        working_dir=image["target_repo_dir"],
        volumes={
            temp_dir: {"bind": image["target_repo_dir"], "mode": "rw"},
        },
    )
    cmd = [
        os.path.join(os.path.join(os.environ.get("HOSTDIR", "/"), "usr/bin/docker")),
        "stats",
        "--format",
        '"{{.CPUPerc}},{{.MemUsage}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}"',
        container.id,
    ]

    dstats_tmppath = os.path.join(temp_dir, ".docker_stats.tmp")
    with open(dstats_tmppath, "w") as dstats_fp:
        p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
        p2 = subprocess.Popen(
            ["ts", '"%Y-%m-%dT%H:%M:%.S"'], stdin=p1.stdout, stdout=dstats_fp
        )
        p1.stdout.close()

        container.start()
        for line in container.logs(stream=True):
            yield line.decode("utf-8")

        ret = container.wait()

        p1.send_signal(signal.SIGTERM)
    p2.wait()
    p1.wait()

    with open(os.path.join(temp_dir, ".stdout"), "wb") as fp:
        fp.write(container.logs(stdout=True, stderr=False))
    with open(os.path.join(temp_dir, ".stderr"), "wb") as fp:
        fp.write(container.logs(stdout=False, stderr=True))
    with open(os.path.join(temp_dir, ".entrypoint"), "w") as fp:
        fp.write(image["entrypoint"])
    # Remove 'clear screen' special chars from docker stats output
    # and save it as new file
    with open(dstats_tmppath, "r") as infp:
        with open(dstats_tmppath[:-4], "w") as outfp:
            for line in infp.readlines():
                outfp.write(re.sub(r"\x1b\[2J\x1b\[H", "", line))
    os.remove(dstats_tmppath)
    container.remove()
    if ret["StatusCode"] != 0:
        return "Error executing recorded run", 500
    yield "\U0001F918 Finished running\n"


def _get_manifest_hash(path):
    manifest_hash = hashlib.md5()
    for alg in ["md5", "sha256"]:
        with open(f"{path}/manifest-{alg}.txt", "rb") as fp:
            manifest_hash.update(fp.read())
    return manifest_hash


def generate_tro(payload_zip, temp_dir):
    """Part of the workflow generating TRO..."""
    yield "\U0001F45B Bagging result\n"
    bdb.make_bag(temp_dir, metadata=TRACE_CLAIMS.copy())
    payload_zip = f"{payload_zip[:-4]}_run"
    shutil.make_archive(payload_zip, "zip", temp_dir)
    digest = _get_manifest_hash(temp_dir).hexdigest().encode()
    shutil.rmtree(temp_dir)
    yield "\U0001F4DC Signing the bag\n"
    with zipfile.ZipFile(f"{payload_zip}.zip", mode="a") as zf:
        zf.comment = str(
            gpg.sign(digest, keyid=GPG_KEYID, passphrase=GPG_PASSPHRASE, detach=False)
        ).encode()
    yield (
        "\U0001F4E9 Your magic bag is available as: "
        f"{os.path.basename(payload_zip)}.zip!\n"
    )


def sanitize_environment(image):
    image.setdefault("entrypoint", "run.sh")
    image.setdefault("target_repo_dir", "/home/jovyan/work")
    image.setdefault("container_user", "jovyan")
    image.setdefault("extra_args", "")


def _set_workdir_ownership(temp_dir):
    for root, dirs, files in os.walk(temp_dir):
        for subdir in dirs:
            os.chown(os.path.join(root, subdir), 1000, 1000)
        for fname in files:
            os.chown(os.path.join(root, fname), 1000, 1000)


@stream_with_context
def magic(payload_zip, image=None):
    """Full workflow."""
    temp_dir = tempfile.mkdtemp(dir=TMP_PATH)
    os.chown(temp_dir, 1000, 1000)  # FIXME: figure out all the uid/gid dance..
    if not image:
        image = {}
    sanitize_environment(image)
    yield from build_image(payload_zip, temp_dir, image)
    yield from run(temp_dir, image)
    yield from generate_tro(payload_zip, temp_dir)
    yield "\U0001F4A3 Done!!!"


@app.route("/", methods=["POST"])
def handler():
    """Either saves payload passed as body or accepts a path to a directory."""
    fname = os.path.join(STORAGE_PATH, f"{str(uuid.uuid4())}.zip")
    if path := request.args.get("path", default="", type=str):
        # Code below is a potential security issue, better not to do it.
        path = os.path.join(os.environ.get("HOSTDIR", "/host"), os.path.abspath(path))
        if not os.path.isdir(path):
            return f"Invalid path: {path}", 400
        shutil.make_archive(fname[:-4], "zip", path)
    if "file" in request.files:
        request.files["file"].save(fname)
    image = {
        "entrypoint": request.args.get("entrypoint", default="run.sh", type=str),
        "container_user": request.args.get("containerUser", default="jovyan", type=str),
        "target_repo_dir": request.args.get(
            "targetRepoDir", default="/home/jovyan/work/workspace", type=str
        ),
        "extra_args": request.args.get("extraArgs", default="", type=str),
    }
    return magic(fname, image=image)


@app.route("/run/<path:path>", methods=["GET"])
def send_run(path):
    """Serve static files from storage dir."""
    return send_from_directory(STORAGE_PATH, path)


@app.route("/verify", methods=["POST"])
def verify_bag():
    """Verify that uploaded bag is signed and valid."""
    if "file" not in request.files:
        return "No bag found", 400
    fname = os.path.join(TMP_PATH, f"{str(uuid.uuid4())}.zip")
    request.files["file"].save(fname)
    temp_dir = tempfile.mkdtemp(dir=TMP_PATH)
    shutil.unpack_archive(fname, temp_dir, "zip")
    try:
        bdb.validate_bag(temp_dir)
    except bagit.BagError:
        return "Invalid bag", 400
    except bagit.BagValidationError:
        return "Bag failed validation", 400

    sig_str = "Signature info:\n"
    with zipfile.ZipFile(fname, mode="r") as zf:
        verified = gpg.verify(zf.comment.decode())
        if not verified:
            raise ValueError("Signature could not be verified")

        sig_info = verified.sig_info[verified.signature_id]
        for key in sig_info:
            sig_str += f"\t{key}: {sig_info[key]}\n"

    sig_str += "\U00002728 Valid and signed bag"
    return sig_str
