# Pinned: ghcr.io/ggml-org/whisper.cpp:main (2025-05-12)
# To update: docker pull ghcr.io/ggml-org/whisper.cpp:main && docker inspect --format='{{.Id}}' ghcr.io/ggml-org/whisper.cpp:main
FROM ghcr.io/ggml-org/whisper.cpp@sha256:9c2cc99647bacfdbb974756297cdc44d272bfbf0986a240c494fbbab800bbdbd

# Download the small model — best speed/accuracy tradeoff for CPU
# (medium is ~2.5x realtime on Ryzen 5 3600; small is ~0.5x realtime)
RUN bash /app/models/download-ggml-model.sh small

EXPOSE 8200

ENV WHISPER_THREADS=""

# Override the base image's ENTRYPOINT which is ["bash", "-c"]
ENTRYPOINT []
CMD ["/bin/sh", "-c", "/app/build/bin/whisper-server --model /app/models/ggml-small.bin --host 0.0.0.0 --port 8200 --threads ${WHISPER_THREADS:-$(nproc)}"]
