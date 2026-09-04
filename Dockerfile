# syntax=docker/dockerfile:1.7
# The caller supplies a multi-platform Python image pinned by registry digest.
# Registry access is confined to the wheelhouse stage. The runtime stage
# installs only hash-locked wheels and the exact local candidate wheel.
ARG PYTHON_IMAGE

FROM ${PYTHON_IMAGE} AS wheelhouse
WORKDIR /build
COPY requirements-base.lock ./requirements-base.lock
RUN python -m pip download \
      --disable-pip-version-check \
      --require-hashes \
      --only-binary=:all: \
      --dest /wheelhouse \
      -r requirements-base.lock
ARG CANDIDATE_WHEEL=dist/psychopathia_mcp-0.1.0a5-py3-none-any.whl
COPY ${CANDIDATE_WHEEL} /wheelhouse/

FROM ${PYTHON_IMAGE} AS runtime
ARG OCI_SOURCE=https://github.com/NellInc/psychopathia-mcp
ARG OCI_REVISION
ARG OCI_VERSION=0.1.0a5
ARG OCI_CREATED
ARG PYTHON_IMAGE
ARG CANDIDATE_WHEEL_SHA256
ARG PACKAGE_SOURCE_SHA256
LABEL org.opencontainers.image.source=${OCI_SOURCE} \
      org.opencontainers.image.revision=${OCI_REVISION} \
      org.opencontainers.image.version=${OCI_VERSION} \
      org.opencontainers.image.created=${OCI_CREATED} \
      org.opencontainers.image.base.name=${PYTHON_IMAGE} \
      org.opencontainers.image.title="psychopathia-mcp" \
      org.opencontainers.image.licenses="MIT AND CC-BY-NC-ND-4.0" \
      org.opencontainers.image.psychopathia.wheel.sha256=${CANDIDATE_WHEEL_SHA256} \
      org.opencontainers.image.psychopathia.package-source.sha256=${PACKAGE_SOURCE_SHA256}
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY requirements-base.lock /tmp/requirements-base.lock
COPY --from=wheelhouse /wheelhouse /tmp/wheelhouse
RUN python -m pip install \
      --no-index \
      --find-links=/tmp/wheelhouse \
      --require-hashes \
      -r /tmp/requirements-base.lock \
    && python -m pip install \
      --no-index \
      --find-links=/tmp/wheelhouse \
      --no-deps \
      /tmp/wheelhouse/psychopathia_mcp-*.whl \
    && psychopathia-mcp --self-check --json \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /tmp/wheelhouse /tmp/requirements-base.lock /root/.cache
USER 65532:65532
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD ["psychopathia-mcp", "--self-check", "--json"]
ENTRYPOINT ["psychopathia-mcp"]
