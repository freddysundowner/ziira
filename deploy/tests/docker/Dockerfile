# Throwaway image for proving that what the installer renders is accepted by a REAL nginx on the distribution's own version
# (Ubuntu 20.04: nginx 1.18, python 3.8), and that the generated environment passes scripts/check_env.py.
# nginx is deliberately NOT preinstalled: the installer must install it itself. Nothing talks to Let's Encrypt.
ARG BASE=ubuntu:24.04
FROM ${BASE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl openssl git rsync xz-utils python3 iproute2 procps \
    && rm -rf /var/lib/apt/lists/*
