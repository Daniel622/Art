#!/usr/bin/env sh
set -eu

APP_DIR="${APP_DIR:-/opt/obscura-studio}"
DATA_DIR="${ART_DATA_DIR:-/var/lib/obscura}"

mkdir -p "$APP_DIR" "$DATA_DIR" "$DATA_DIR/images"
cp -R server.py static deploy README.md "$APP_DIR"/

if [ ! -f "$DATA_DIR/.env.example" ]; then
  cat > "$DATA_DIR/.env.example" <<EOF
ART_HOST=127.0.0.1
ART_PORT=8080
ART_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
ART_DATA_DIR=$DATA_DIR
ART_IMAGE_DIR=$DATA_DIR/images
ART_ADMIN_USER=admin
ART_ADMIN_PASSWORD=replace-me
EOF
fi

echo "Installed to $APP_DIR. Existing data in $DATA_DIR was preserved."
