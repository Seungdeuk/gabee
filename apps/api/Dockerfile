FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

# 모델 파일은 저장소에 없다(data/ 는 .gitignore). 빌드하는 PC 의 apps/api/data/models/ 아래에
# 압축을 푼 폴더 3개(doc-classifier, e5-small-ft, ner-koelectra-small-v2b)를 두고 빌드한다.
# 폴더가 없으면 이 줄에서 빌드가 실패한다.
COPY data/models ./data/models
ENV DOC_CLASSIFIER_DIR=/srv/data/models/doc-classifier \
    EMBED_MODEL_DIR=/srv/data/models/e5-small-ft \
    PRIVACY_NER_MODEL_DIR=/srv/data/models/ner-koelectra-small-v2b

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
