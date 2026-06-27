FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir gpxpy numpy Pillow requests

COPY gpx_map.py .

ENTRYPOINT ["python", "gpx_map.py"]
