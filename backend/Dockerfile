FROM python:3.12-slim

# git is required: the evolution analyzer shells out to it
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# In compose the whole repo is bind-mounted over /app (live reload, and the
# default "../datasets/..." paths resolve). This COPY makes the image usable on its own too.
COPY . /app

# Repos mounted from the host are owned by another user; don't let git refuse them
RUN git config --global --add safe.directory '*'

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
