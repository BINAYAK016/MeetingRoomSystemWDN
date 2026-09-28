FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN DJANGO_SECRET_KEY=build-only DJANGO_ALLOWED_HOSTS=localhost \
    POSTGRES_DB=build-only POSTGRES_USER=build-only \
    POSTGRES_PASSWORD=build-only POSTGRES_HOST=db \
    python manage.py collectstatic --noinput

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
