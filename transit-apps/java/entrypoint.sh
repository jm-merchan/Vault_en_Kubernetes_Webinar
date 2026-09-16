#!/bin/sh
set -eu

CACERT="${VAULT_CACERT:-/certs/ca.pem}"
CLIENT_CERT="${VAULT_CLIENT_CERT:-/certs/client.pem}"
CLIENT_KEY="${VAULT_CLIENT_KEY:-/certs/client-key.pem}"

rm -f /tmp/truststore.jks /tmp/client.p12

keytool -importcert -noprompt -alias vault \
  -file "$CACERT" \
  -keystore /tmp/truststore.jks \
  -storepass changeit

openssl pkcs12 -export \
  -in "$CLIENT_CERT" \
  -inkey "$CLIENT_KEY" \
  -out /tmp/client.p12 \
  -name transit \
  -passout pass:changeit

export VAULT_TRUSTSTORE="file:/tmp/truststore.jks"
export VAULT_KEYSTORE="file:/tmp/client.p12"
unset DEBUG

exec java -jar /app.jar
