FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -u 10001 -m app
USER 10001
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
