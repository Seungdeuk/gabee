FROM python:3.12-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

# 모델 파일은 저장소에 없다(data/ 는 .gitignore). 빌드하는 PC 의 apps/api/data/models/ 아래에
# 압축을 푼 폴더 3개(doc-classifier, e5-small-ft, ner-koelectra-small-r11b-s21)를 두고 빌드한다.
# 폴더가 없으면 이 줄에서 빌드가 실패한다.
COPY data/models ./data/models
ENV DOC_CLASSIFIER_DIR=/srv/data/models/doc-classifier \
    EMBED_MODEL_DIR=/srv/data/models/e5-small-ft \
    PRIVACY_NER_MODEL_DIR=/srv/data/models/ner-koelectra-small-r11b-s21 \
    PRIVACY_NER_MODEL_FILE=model.onnx \
    PRIVACY_NER_MODE=required

# NER 모델(R11 B-new seed 21)이 확정본이 아니면 빌드를 실패시킨다(다른 폴더·파일이 섞여 들어가는 것을 막는다).
# 모델을 바꿀 때만 이 해시와 위 폴더 이름을 함께 바꾼다(docs/security/NER_R11_OPS_DEPLOY_HANDOFF.md).
RUN printf '%s  %s\n' \
      3831601b7ffb6093a8d1b8c832e46ad140712c6e402f17b3054c3ec0f9ae4c94 data/models/ner-koelectra-small-r11b-s21/model.onnx \
      d5c7a9a8996aca4fee55a3664381b012bd7dbb3e190061b2591c02502b7171b6 data/models/ner-koelectra-small-r11b-s21/tokenizer.json \
      f5cf8bd55bf4c31df0da444131a7b68ff0ace3e482ca7dad6e2f55f3fd216fe4 data/models/ner-koelectra-small-r11b-s21/labels.json \
      0157e8bf854e3b492adead91332526ff09c4f2381208d711f9d7c3429ac2cc74 data/models/ner-koelectra-small-r11b-s21/model_card.json \
    | sha256sum -c -

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
