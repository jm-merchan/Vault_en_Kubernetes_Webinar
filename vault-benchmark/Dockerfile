FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY vault-benchmark /usr/local/bin/vault-benchmark
ENTRYPOINT ["vault-benchmark"]
