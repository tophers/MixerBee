FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.python.org -r requirements.txt
RUN mkdir /config
COPY . .
EXPOSE 9000
CMD ["uvicorn", "web:app", "--host", "0.0.0.0", "--port", "9000"]
