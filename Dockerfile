FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "obsidian_livesync_mcp.server"]
