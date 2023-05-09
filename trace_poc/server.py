"""Main TRACE PoC API layer."""
import datetime
import hashlib
import json
import os
import random
import re
import shutil
import signal
import string
import subprocess
import tempfile
import uuid
import zipfile

import bagit
import docker
import gnupg
import magic
import rfc3161ng
from bdbag import bdbag_api as bdb
from flask import (Flask, render_template, request, send_from_directory,
                   stream_with_context)
from pyasn1.codec.der import encoder

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

TRACE_CLAIMS["id"] = "https://server.trace-poc.xyz/"
TRACE_CLAIMS["gpg_keyid"] = GPG_KEYID
TRACE_CLAIMS["gpg_fingerprint"] = GPG_FINGERPRINT


def build_image(temp_dir, image):
    """Part of the workflow resposible for building image."""
    yield "\U0001F64F Start building\n"
    # For WT specific buildpacks we would need to inject env.json
    # with open(os.path.join(temp_dir, "environment.json")) as fp:
    #     json.dump({"config": {"buildpack": "PythonBuildPack"}}, fp)
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
    # container.remove()
    if ret["StatusCode"] != 0:
        return "Error executing recorded run", 500
    yield "\U0001F918 Finished running\n"


def _get_manifest_hash(path):
    manifest_hash = hashlib.md5()
    for alg in ["md5", "sha256"]:
        with open(f"{path}/manifest-{alg}.txt", "rb") as fp:
            manifest_hash.update(fp.read())
    return manifest_hash


def _generate_declaration(bag_after, bag_before, zipname, start_time, end_time):
    """
    Generates a TRO declaration file for the TRO payload.

    A TRO declaration file is a JSON file that MUST contain the following:
        - a payload fingerprint
        - the unique id and public key of Trace System (TRS) that produced the TRO
        - an Authorized Digital Time Stamp (ADTS) of the TRO

    A TRO declaration file MAY contain the following:
        - TRACE-vocabulary expressed claims about the associated TRS.
        - TRACE-vocabulary expressed claims about this specific TRO.
        - Identification of the individual digital artifacts and
          bitstreams comprising the TRO payload
    """
    zip_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://server.trace-poc.xyz/{zipname}_run.zip"
    )
    declaration = {
        "@context": [
            {
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "trov": "https://w3id.org/trace/2023/05/trov#",
                "@base": f"arcp://uuid,{zip_id}/",
            }
        ],
    }

    arrangement_seq = 0
    artifacts = {}
    for root in [bag_before, bag_after]:
        with open(f"{root}/manifest-sha256.txt", "r") as fp:
            for line in fp:
                digest, path = line.strip().split("  ")
                if digest not in artifacts:
                    artifacts[digest] = {}
                artifacts[digest][arrangement_seq] = path
        arrangement_seq += 1

    magic_wrapper = magic.Magic(mime=True, uncompress=True)

    hasArtifacts = [
        {
            "@id": f"composition/1/artifact/{art_seq}",
            "@type": "trov:ResearchArtifact",
            "trov:mimeType": magic_wrapper.from_file(
                f"{root}/{list(artifacts[digest].values())[0]}"
            )
            or "application/octet-stream",
            "trov:sha256": digest,
        }
        for art_seq, digest in enumerate(artifacts.keys())
    ]
    # sha256 of a concatenation of the sorted digests
    # of the individual digital artifacts and bitstreams
    composition_fingerprint = hashlib.sha256(
        "".join(sorted([art["trov:sha256"] for art in hasArtifacts])).encode("utf-8")
    ).hexdigest()

    composition = {
        "@id": "composition/1",
        "@type": "trov:ArtifactComposition",
        "trov:hasFingerprint": {
            "@id": "fingerprint",
            "@type": "trov:CompositionFingerprint",
            "trov:sha256": composition_fingerprint,
        },
        "trov:hasArtifact": hasArtifacts,
    }

    arrangements = []
    for iarr, arrangement in enumerate(("Initial arrangement", "Final arrangement")):
        iseq = 0
        locus = []
        for artifact in hasArtifacts:
            if iarr in artifacts[artifact["trov:sha256"]]:
                # hasLocation needs to exclude the bag's "data/" prefix
                locus.append(
                    {
                        "@id": f"arrangement/{iarr}/locus/{iseq}",
                        "@type": "trov:ArtifactLocus",
                        "trov:hasArtifact": {
                            "@id": artifact["@id"],
                        },
                        "trov:hasLocation": artifacts[artifact["trov:sha256"]][iarr][5:],
                    }
                )
                iseq += 1

        arrangements.append(
            {
                "@id": f"arrangement/{iarr}",
                "@type": "trov:ArtifactArrangement",
                "rdfs:comment": arrangement,
                "trov:hasLocus": locus,
            }
        )

    declaration["@graph"] = [
        {
            "@id": "tro",
            "@type": "trov:TransparentResearchObject",
            "trov:wasAssembledBy": {
                "@id": "trs",
                "@type": "trov:TrustedResearchSystem",
                "rdfs:comment": "TRS Prototype",
                "trov:publicKey": gpg.export_keys(GPG_KEYID),
                "trov:hasCapability": [
                    {
                        "@id": "trs/capability/1",
                        "@type": "trov:CanProvideInternetIsolation",
                    }
                ],
            },
            "trov:hasAttribute": [
                {
                    "@id": "tro/attribute/1",
                    "@type": "trov:IncludesAllInputData",
                    "trov:warrantedBy": {"@id": "trp/1/attribute/1"},
                }
            ],
            "trov:hasComposition": composition,
            "trov:hasArrangement": arrangements,
            "trov:hasPerformance": {
                "@id": "trp/1",
                "@type": "trov:TrustedResearchPerformance",
                "rdfs:comment": "Workflow execution",
                "trov:wasConductedBy": {"@id": "trs"},
                "trov:startedAtTime": start_time.isoformat(),
                "trov:endedAtTime": end_time.isoformat(),
                "trov:accessedArrangement": {"@id": "arrangement/0"},
                "trov:modifiedArrangement": {"@id": "arrangement/1"},
                "trov:hadPerformanceAttribute": {
                    "@id": "trp/1/attribute/1",
                    "@type": "trov:InternetIsolation",
                    "trov:warrantedBy": {"@id": "trs/capability/1"},
                },
            },
        },
    ]

    return declaration


def generate_tro(payload_zip, temp_dir, initial_dir, start_time, end_time):
    """Part of the workflow generating TRO..."""
    storage_dir = os.path.dirname(payload_zip)
    basename = os.path.basename(payload_zip)[:-4]

    yield "\U0001F45B Bagging result\n"
    bdb.make_bag(temp_dir, metadata=TRACE_CLAIMS.copy())
    yield "\U0001F4C2 Computing digests\n"
    tro_declaration = _generate_declaration(
        temp_dir, initial_dir, basename, start_time, end_time
    )
    yield "\U0001F4C2 Signing the manifest\n"
    trs_signature = gpg.sign(
        json.dumps(tro_declaration, indent=2, sort_keys=True),
        keyid=GPG_KEYID,
        passphrase=GPG_PASSPHRASE,
        detach=True,
    )

    yield "\U0001F4C2 Writing the manifest\n"
    with open(f"{storage_dir}/{basename}.jsonld", "w") as fp:
        json.dump(tro_declaration, fp, indent=2, sort_keys=True)
    with open(f"{storage_dir}/{basename}.sig", "w") as fp:
        fp.write(str(trs_signature))
    yield "\U0001F553 Timestamping the TRO Declaration and TRS Signature\n"
    rt = rfc3161ng.RemoteTimestamper("https://freetsa.org/tsr", hashname="sha512")
    ts_data = {
        "tro_declaration": hashlib.sha512(
            json.dumps(tro_declaration, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "trs_signature": hashlib.sha512(str(trs_signature).encode("utf-8")).hexdigest(),
    }
    tsr = rt(data=json.dumps(ts_data).encode(), return_tsr=True)
    with open(f"{storage_dir}/{basename}.tsr", "wb") as fs:
        fs.write(encoder.encode(tsr))
    yield "\U0001F4C2 Zipping the bag\n"
    result_zip = os.path.join(storage_dir, f"{basename}_run")
    shutil.make_archive(result_zip, "zip", os.path.join(temp_dir, "data"))
    shutil.rmtree(temp_dir)
    yield (
        "\U0001F4E9 Your magic bag is available as: "
        f"{os.path.basename(result_zip)}.zip!\n"
    )


def sanitize_environment(image):
    image.setdefault("entrypoint", "run.sh")
    image.setdefault("target_repo_dir", "/home/jovyan/work")
    image.setdefault("container_user", "jovyan")
    image.setdefault("extra_args", "")


def _set_workdir_ownership(temp_dir):
    # FIXME: figure out all the uid/gid dance..
    yield f"\U0001F45B Setting ownership of the {temp_dir}\n"
    os.chown(temp_dir, 1000, 1000)
    for root, dirs, files in os.walk(temp_dir):
        for subdir in dirs:
            os.chown(os.path.join(root, subdir), 1000, 1000)
        for fname in files:
            os.chown(os.path.join(root, fname), 1000, 1000)


def bag_initial_state(temp_dir, initial_dir):
    """Bag the initial state of the payload."""
    yield "\U0001F45B Bagging initial state\n"
    shutil.copytree(temp_dir, initial_dir, dirs_exist_ok=True)
    bdb.make_bag(initial_dir, metadata=TRACE_CLAIMS.copy())


@stream_with_context
def magic_workflow(path_to_zip, image=None):
    """Full workflow."""
    # unpack the payload
    temp_dir = tempfile.mkdtemp(dir=TMP_PATH)
    shutil.unpack_archive(path_to_zip, temp_dir, "zip")
    yield from _set_workdir_ownership(temp_dir)
    if os.path.exists(f"{temp_dir}/.git"):
        shutil.rmtree(f"{temp_dir}/.git")
    # prepare image settings
    if not image:
        image = {}
    sanitize_environment(image)

    initial_dir = tempfile.mkdtemp(dir=TMP_PATH)

    yield from bag_initial_state(temp_dir, initial_dir)
    yield from build_image(temp_dir, image)
    start_time = datetime.datetime.utcnow()
    yield from run(temp_dir, image)
    end_time = datetime.datetime.utcnow()
    yield from generate_tro(path_to_zip, temp_dir, initial_dir, start_time, end_time)
    yield "\U0001F4A3 Done!!!"


@app.route("/", methods=["GET"])
def default_html_index():
    """Default index page."""
    data = {
        "trace_server_id": "https://server.trace-poc.xyz",
        "trace_server_public_key": GPG_FINGERPRINT,
        "fnames": [_[:-4] for _ in os.listdir(STORAGE_PATH) if _.endswith(".sig")],
    }
    return render_template("index.html", **data)


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
    return magic_workflow(fname, image=image)


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
