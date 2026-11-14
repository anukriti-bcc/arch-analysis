FROM python:3.12-slim

# git is REQUIRED at runtime: the evolution analyzer shells out to it.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # Repositories mounted from the host are owned by a different user; without this
    # git refuses them ("dubious ownership") and history evidence silently disappears.
    && git config --system --add safe.directory '*'

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
