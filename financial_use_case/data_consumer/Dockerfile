FROM python:3.11-slim
WORKDIR /app

COPY financial_use_case/data_consumer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY financial_use_case/data_consumer/ /app
CMD ["python", "consumer.py"]