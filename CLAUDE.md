# BURY RICH AI SHORTFORM STUDIO — 개발 규칙 (Claude Code용)

운영자는 개발자가 아니며 스마트폰만 사용한다. 모든 보고는 **한국어**, 전문 용어는 쉽게 풀어서 설명한다.

## 구조
- `app/main.py` 웹 API + 화면 제공 (FastAPI)
- `app/worker.py` 백그라운드 작업 처리기 (영상 제작, 참고 영상 분석, 백업)
- `app/services/` 기능 모듈
  - `analyzer.py` 원본 영상 분석(밝기/선명도/흔들림/중복/피사체 위치)
  - `asr.py` 음성 인식(faster-whisper, 무료)
  - `copywriter.py` 문구 생성(규칙 기반 무료 + Claude 선택)
  - `benchmark.py` 인기 숏폼 참고 자료·패턴, YouTube API
  - `planner.py` 편집 계획(plan JSON) 생성 — 수정/재렌더링은 plan을 고쳐서 수행
  - `editor.py` FFmpeg 렌더링 엔진
  - `costs.py` 원가 계산(실측/추정 구분), `catalog.py` 업종·스타일 카탈로그
- `app/static/` 모바일 화면 (`index.html` 고객용, `admin.html` 운영자용)
- DB: SQLite (`DATA_DIR/studio.db`), 스키마는 `app/db.py`

## 반드시 지킬 것
1. 기존에 동작하는 기능을 임의로 삭제·변경하지 않는다. DB 컬럼은 추가만 하고(ALTER TABLE ADD COLUMN), 삭제하지 않는다.
2. 변경 후 `python -m pytest -q tests` 를 실행해 모두 통과해야 커밋한다. 새 기능에는 테스트를 추가한다.
3. 가짜 조회수·후기·매출·분석 결과를 실제처럼 표시하지 않는다. 확인 불가 값은 `None`/"확인 불가"로 둔다.
4. 고객이 제공하지 않은 가격·할인·효능·후기를 문구로 만들지 않는다.
5. API 키는 환경변수로만 다룬다. 코드·커밋에 넣지 않는다.
6. 유료 API 연결이나 비용이 늘어나는 변경은 운영자 승인 후 진행한다.
7. 음악은 상업적 이용 허용 음원만, 라이선스 기록과 함께 사용한다.
8. 작업은 `claude/` 브랜치에서 하고, 운영 배포는 운영자가 승인한 뒤 main 에 병합한다.

## 로컬 실행/테스트
```
pip install -r requirements.txt          # ffmpeg, fonts-nanum 필요
python scripts/make_test_media.py test_media
ADMIN_PASSWORD=test1234 uvicorn app.main:app --port 8000 &
python -m app.worker &
python -m pytest -q tests
```
