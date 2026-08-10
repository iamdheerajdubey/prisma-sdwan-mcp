FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY prisma_sdwan_mcp/ ./prisma_sdwan_mcp/
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER 10001:10001
EXPOSE 8000
CMD ["prisma-sdwan-mcp", "--transport", "stdio"]
