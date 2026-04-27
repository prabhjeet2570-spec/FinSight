# Optional local container. The normal development workflow uses a Python venv.
FROM python:3.12-slim
WORKDIR /finsight
COPY backend/requirements.txt /finsight/backend/requirements.txt
RUN pip install --no-cache-dir -r /finsight/backend/requirements.txt
COPY backend /finsight/backend
COPY data /finsight/data
COPY scripts /finsight/scripts
ENV PYTHONPATH=/finsight/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
