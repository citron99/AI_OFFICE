FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
# The project is not installed into site-packages, so imports resolve via /app regardless of cwd.
ENV PYTHONPATH=/app
RUN useradd --create-home office && mkdir -p /app/uploads && chown office:office /app/uploads
USER office
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
