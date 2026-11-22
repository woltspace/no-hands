ARG ASTERISK_IMAGE=shellphone-voice:local
FROM ${ASTERISK_IMAGE}
RUN apk add --no-cache python3
COPY transport_repro.py /transport_repro.py
CMD ["python3", "/transport_repro.py"]
