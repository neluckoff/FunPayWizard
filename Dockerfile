FROM python:3.10-slim

WORKDIR /app
COPY . /app

ENV PYTHONUNBUFFERED=1

RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

CMD ["python", "main.py"]
