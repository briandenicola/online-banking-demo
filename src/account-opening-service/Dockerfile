FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

COPY ./app ./app
COPY ./pyproject.toml ./

RUN pip install --no-cache-dir --root-user-action=ignore .

# Create python symlink for compatibility (MCR azurelinux only has python3)
RUN ln -sf /usr/bin/python3 /usr/bin/python

EXPOSE 8004

USER 1001

# Worker deployment overrides CMD with: python -m app.worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
