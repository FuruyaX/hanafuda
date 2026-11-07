# 開発用イメージ: ソースはバインドマウント、Pyodide とビルド結果は名前付きボリューム（/data）
# ブラウザの Pyodide 314 と同じ Python 3.14 系でテストする
FROM python:3.14-slim
RUN pip install --no-cache-dir "pytest==8.*" \
 && useradd -m -u 1000 app \
 && mkdir -p /data && chown app:app /data
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BUILD_DIR=/data/dist \
    PYODIDE_DIR=/data/pyodide
WORKDIR /app
USER app
EXPOSE 8000
CMD ["python", "scripts/dev_server.py"]
