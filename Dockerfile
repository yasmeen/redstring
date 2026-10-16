FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY redstring ./redstring
COPY data ./data
RUN pip install --no-cache-dir -e .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# Seeds on boot so a fresh deploy always starts from world.json.
CMD ["sh", "-c", "if [ \"$REDSTRING_READONLY\" = \"1\" ]; then redstring demo; else redstring seed; fi && redstring serve --host 0.0.0.0 --port ${PORT:-8000}"]
