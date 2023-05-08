FROM python:3.10-slim

RUN apt-get update -qqy \
  && DEBIAN_FRONTEND=noninteractive apt-get -qy install \
    moreutils gnupg libmagic1 \
  && apt-get -qqy clean all \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . /app
RUN python3 -m pip install /app
ENTRYPOINT ["trace-poc-serve"]
