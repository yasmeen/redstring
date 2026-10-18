FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY redstring ./redstring
COPY data ./data
RUN pip install --no-cache-dir -e .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# Retry seeding until FalkorDB is ready; public deployments start read-only with the finished demo.
ENV REDSTRING_READONLY=1
CMD ["sh", "-c", "if [ \"$REDSTRING_READONLY\" = \"1\" ]; then INIT='redstring demo'; else INIT='redstring seed'; fi; until $INIT; do echo 'Waiting for FalkorDB...' >&2; sleep 2; done; exec redstring serve --host 0.0.0.0 --port ${PORT:-8000}"]
