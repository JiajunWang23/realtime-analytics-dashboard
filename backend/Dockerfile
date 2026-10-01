# Build context: repository root (so the website tracker can be served from /rta.js).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
COPY tracker/ tracker/
RUN useradd -u 10001 -m app
USER 10001
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
