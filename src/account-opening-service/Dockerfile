FROM python:3.11-slim

WORKDIR /app

COPY ./app ./app
COPY ./pyproject.toml ./

RUN pip install --no-cache-dir --root-user-action=ignore .

EXPOSE 8004

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

# Worker deployment overrides CMD with: python -m app.worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
