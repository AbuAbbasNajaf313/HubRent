FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# create_app() folgt in Meilenstein 4 (Flask-Web-Schicht)
CMD ["gunicorn", "-b", "0.0.0.0:8000", "app:create_app()"]
