FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY matchmaking-assistant-final-withUI.py .

EXPOSE 8501

CMD ["streamlit", "run", "matchmaking-assistant-final-withUI.py",
     "--server.port=8501",
     "--server.address=0.0.0.0"]
