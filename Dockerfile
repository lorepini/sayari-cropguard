FROM python:3.11-slim

# rasterio/pyproj wheels bundle their native libs (GDAL/PROJ) — no apt needed.
# Keeping curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8051

CMD ["python", "app/app.py"]
