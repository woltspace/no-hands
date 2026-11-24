FROM alpine@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000
RUN apk add --no-cache asterisk=22.11.0-r1 asterisk-sample-config=22.11.0-r1 asterisk-opus=22.11.0-r1
CMD ["asterisk", "-f", "-vvv"]
