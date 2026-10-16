# Throwaway Ubuntu 24.04 image for proving that what the installer renders is accepted by a REAL nginx, and that the
# generated environment passes scripts/check_env.py. Nothing here talks to Let's Encrypt or needs systemd.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg openssl git rsync xz-utils build-essential python3 python3-venv python3-pip nginx certbot \
      logrotate ufw fail2ban iproute2 procps \
    && rm -rf /var/lib/apt/lists/*
