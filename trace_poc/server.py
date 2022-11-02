import time
from flask import Flask, stream_with_context, flash, request

app = Flask(__name__)


def build_image():
    yield "Start building\n"
    time.sleep(2)
    yield "Finished building\n"


def run():
    yield "Start running\n"
    time.sleep(2)
    yield "Finished runnning\n"


def generate_tro():
    yield "Performing the magic\n"
    time.sleep(2)


@stream_with_context
def magic(placeholder):
    yield from build_image()
    yield from run()
    yield from generate_tro()
    yield f"Your magic bag is available as {placeholder}!\n"


@app.route("/", methods=["GET", "POST"])
def hello():
    if request.method == "POST":
        if "file" in request.files:
            request.files["file"].save("/tmp/foo.zip")
    return magic("foo")
