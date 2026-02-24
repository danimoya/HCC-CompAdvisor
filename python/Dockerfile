FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application package
COPY hcc_advisor/ ./hcc_advisor/

# Ensure hcc_advisor is importable as a package
ENV PYTHONPATH=/app

# Create logs directory
RUN mkdir -p logs

# Expose Streamlit port
EXPOSE 8501

# Run Streamlit
CMD ["streamlit", "run", "hcc_advisor/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
