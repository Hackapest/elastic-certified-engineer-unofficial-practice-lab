#!/bin/bash
# Generates one CA and a certificate per node into /certs. Runs once per
# install as the `certs` service; does nothing if the certificates exist.
set -e

certutil=/usr/share/elasticsearch/bin/elasticsearch-certutil
cd /certs

if [ ! -f ca/ca.crt ]; then
  echo "Generating CA"
  $certutil ca --silent --pem -out /tmp/ca.zip
  unzip -q /tmp/ca.zip -d /certs
fi

if [ ! -f es-a1/es-a1.crt ]; then
  echo "Generating node certificates"
  $certutil cert --silent --pem -out /tmp/certs.zip \
    --in /usr/share/elasticsearch/ece/instances.yml \
    --ca-cert /certs/ca/ca.crt --ca-key /certs/ca/ca.key
  unzip -q /tmp/certs.zip -d /certs
fi

chown -R 1000:0 /certs
find /certs -type d -exec chmod 750 {} \;
find /certs -type f -exec chmod 640 {} \;
echo "Certificates ready"
