# Optional: run Projecute in a container on any Docker host.
# Build:  docker build -t projecute .
# Run:    docker run -p 8000:8000 -e GROQ_API_KEY=... projecute   then open http://localhost:8000
FROM python:3.11-slim

# Run as an unprivileged user.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000
WORKDIR /home/user/app

# CPU-only PyTorch keeps the image small; then the rest of the dependencies.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r requirements.txt

# Download the embedding model at build time so the first conflict check is fast.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Then the app code (secrets and local data are excluded by .dockerignore).
COPY --chown=user . .
RUN mkdir -p data

# Listen on port 8000 and start the server.
EXPOSE 8000
CMD ["python", "main.py"]
