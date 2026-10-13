FROM lofi-vibe-coding:f866782301118aa860027b4138e823e36aeaf7aa
ARG SOURCE_SHA
LABEL org.opencontainers.image.version="1.5.0" lofi.qc.version="3.0.0" lofi.source.sha256="${SOURCE_SHA}" lofi.base.revision="f866782301118aa860027b4138e823e36aeaf7aa" org.opencontainers.image.revision="qc-v3-${SOURCE_SHA}"
COPY studio /app/studio
COPY web /app/web
COPY test_qc.py integration_qc.py /app/
USER 10002
