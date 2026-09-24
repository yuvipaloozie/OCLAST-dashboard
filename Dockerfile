# Stage 1: Build React Frontend
FROM node:20-alpine as frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build FastAPI Backend
FROM python:3.10-slim
WORKDIR /app

# Install system dependencies for OpenCV and ONNX
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY api.py .
COPY oclast/ ./oclast/
COPY oclast_model.onnx .

# Copy built frontend assets to be served by FastAPI
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Expose API port
EXPOSE 8000

# Run FastAPI with Uvicorn
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
