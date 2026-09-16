FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir hvac==2.4.0
COPY app.py .
ENV PYTHONUNBUFFERED=1 LOOP_INTERVAL=20
CMD ["python", "app.py"]
