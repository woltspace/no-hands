FROM alpine@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000 AS audiosocket-build
RUN apk add --no-cache asterisk-dev=22.11.0-r1 build-base util-linux-dev
WORKDIR /build
ADD --checksum=sha256:9589078232e23f3b3e366cc30207cc54446886f785f280f2ff35e922e2b3faee https://raw.githubusercontent.com/asterisk/asterisk/22.11.0/res/res_audiosocket.c res_audiosocket.c
COPY patches/asterisk-audiosocket-read.patch .
RUN patch -p1 < asterisk-audiosocket-read.patch && \
    cc -shared -fPIC -O2 -DAST_MODULE=\"res_audiosocket\" \
    -DAST_MODULE_SELF_SYM=__internal_res_audiosocket_self \
    -o res_audiosocket.so res_audiosocket.c -luuid

FROM alpine@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000 AS asterisk-stock
RUN apk add --no-cache asterisk=22.11.0-r1 asterisk-sample-config=22.11.0-r1 asterisk-opus=22.11.0-r1

FROM asterisk-stock AS runtime
COPY --from=audiosocket-build /build/res_audiosocket.so /usr/lib/asterisk/modules/res_audiosocket.so
CMD ["asterisk", "-f", "-vvv"]
