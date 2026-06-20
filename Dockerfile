FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY cf2amp /app/cf2amp
COPY cf2amp_web /app/cf2amp_web
RUN pip install --no-cache-dir .

EXPOSE 8080

ENTRYPOINT ["cf2amp"]
