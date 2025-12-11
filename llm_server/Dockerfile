FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Use repository requirements if present; keep image small
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt gunicorn

# Copy the contents of the llm_server build context into the image
COPY . /app

EXPOSE 8000
ENV PORT=8000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "app:app"]
