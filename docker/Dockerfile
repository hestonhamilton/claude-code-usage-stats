FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client rsync \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin cus

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir '.[web,worker]' \
    && mkdir -p /data /staging \
    && chown -R cus:cus /app /data /staging

USER cus

CMD ["uvicorn", "cus.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
