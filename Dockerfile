FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir .
CMD ["prisma-sdwan-mcp-v2", "--transport", "stdio"]
