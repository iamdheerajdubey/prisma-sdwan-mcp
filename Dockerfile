# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastmcp prisma-sase python-dotenv pyyaml jsonschema

# Copy the server script
COPY prisma_sdwan_mcp_server.py .
COPY schema.json .

# Expose the port for SSE/HTTP modes
EXPOSE 8000

# Default command to run the server (defaulting to stdio, override for sse)
ENTRYPOINT ["python", "prisma_sdwan_mcp_server.py"]
