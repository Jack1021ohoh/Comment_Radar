# Comment Radar on Cloud Run. The sentiment model is downloaded at build time, so a cold start doesn't wait for it.
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HOME=/app/.hf
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv run --no-dev python -m radar_mcp.sentiment --preload
ENV HOST=0.0.0.0 PORT=8080
CMD ["uv", "run", "--no-dev", "app.py"]
