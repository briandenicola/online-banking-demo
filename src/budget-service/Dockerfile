FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

COPY ./app ./app
COPY ./pyproject.toml ./

RUN pip install --no-cache-dir --root-user-action=ignore .

EXPOSE 8003

USER 1001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]