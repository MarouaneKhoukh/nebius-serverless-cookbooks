FROM python:3.12.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY media_search ./media_search
COPY scripts/make_sample_media.py ./scripts/make_sample_media.py
RUN useradd --uid 10001 --create-home demo && mkdir /data && chown demo:demo /data
USER demo
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "media_search", "serve", "--host", "0.0.0.0", "--port", "8080"]
