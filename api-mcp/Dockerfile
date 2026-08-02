# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the server package and compatibility entry point
COPY prisma_sdwan_mcp_server.py .
COPY prisma_sdwan_mcp ./prisma_sdwan_mcp

# Run the server without root privileges
RUN useradd --create-home --uid 10001 appuser \
	&& chown -R appuser:appuser /app
USER appuser

# Expose the port for SSE/HTTP modes
EXPOSE 8000

# Default command to run the server (defaulting to stdio, override for sse)
ENTRYPOINT ["python", "prisma_sdwan_mcp_server.py"]
