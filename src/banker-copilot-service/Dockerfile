FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

COPY ./src/banker-copilot-service/app ./app
COPY ./src/banker-copilot-service/pyproject.toml ./

# The tool manifest and the role hierarchy are CONFIGURATION, not image content.
# They are baked in so the container starts standalone, and both are overridable by a
# read-only bind mount / ConfigMap at the same paths.
COPY ./config/copilot-tools.yaml ./config/copilot-tools.yaml
COPY ./src/user-service/config/role-hierarchy.yaml ./config/role-hierarchy.yaml

RUN pip install --no-cache-dir --root-user-action=ignore .

RUN ln -sf /usr/bin/python3 /usr/bin/python

EXPOSE 8005

USER 1001

# Shell form so COPILOT_PORT is honoured. The platform lane owns the port and the gateway
# route; 8005 is the default it declared, not a value this image gets to decide on its own.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${COPILOT_PORT:-8005}
