FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY cf2amp /app/cf2amp
RUN pip install --no-cache-dir .

ENTRYPOINT ["cf2amp"]
