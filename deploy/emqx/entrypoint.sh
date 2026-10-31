#!/bin/sh
# Генерира bootstrap файл за authn (ingest потребителя) от env и стартира EMQX.
# Superuser е само ingest клиентът на MeshGate — той прави wildcard subscription.
set -eu
mkdir -p /opt/emqx/bootstrap
cat > /opt/emqx/bootstrap/authn.json <<EOF
[
  {"user_id": "${EMQX_INGEST_USER}", "password": "${EMQX_INGEST_PASSWORD}", "is_superuser": true}
]
EOF
chmod 600 /opt/emqx/bootstrap/authn.json
exec "$@"
