FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY redstring ./redstring
COPY data ./data
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# Seeds on boot so a fresh deploy always starts from world.json.
CMD ["sh", "-c", "redstring seed && redstring serve --host 0.0.0.0 --port ${PORT:-8000}"]
