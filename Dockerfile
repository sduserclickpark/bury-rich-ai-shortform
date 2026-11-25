# BURY RICH AI SHORTFORM STUDIO — 웹 서버 + 영상 처리 워커를 하나의 컨테이너에서 실행
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data APP_ENV=production
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-nanum ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')" || exit 1
CMD ["sh", "scripts/start.sh"]
