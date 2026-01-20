FROM python:3.11-slim
WORKDIR /app

COPY financial_use_case/pos_client/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY financial_use_case/pos_client/ /app
CMD ["python", "client.py"]
