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

# 가족방 사진 판별용 SigLIP2(ONNX, docs/adr/0025). 로컬 OCR(RapidOCR)은 이미지에 없다. 모델은 저장소에 없다: 빌드하는 PC 의 apps/api/data/models/siglip2-onnx/ 에
# siglip2_vision.onnx(371,816,797 B)와 head.json(241,529 B)을 둔다(위 COPY 가 함께 가져간다). 출처: google/siglip2-base-patch16-224 를 ONNX 로 바꾼 산출물(가중치·문장·임계값 고정).
# 폴더가 있으면 전체 SHA-256 을 검증하고(다르면 빌드 실패) 검증 기록을 남긴다. 없으면 경고만 남기고 모델 없이 빌드한다: 서버가 시작할 때
# `photo model status=missing` 을 로그로 남기고, 사진 판별은 unsure(스위치 꺼짐)·failed(스위치 켜짐)가 되어 문서·일반으로 확정하지 않는다.
# 이 ENV 는 모델 위치만 정한다. 판별 스위치(PHOTO_CLASSIFY_SIGLIP)와 Claude 읽기(INGEST_LLM_OCR)는 배포 설정에서 정한다.
ENV PHOTO_CLASSIFY_MODEL_DIR=/srv/data/models/siglip2-onnx
RUN if [ -d data/models/siglip2-onnx ]; then \
      printf '%s  %s\n' \
        52e01513b5b98b80056f10bcce72e9568e050070e296ea6d557afb5b06d61949 data/models/siglip2-onnx/siglip2_vision.onnx \
        2a177cbe0fdd815447bcf2e089dbc96dbf906242e0d07d4c7831f90bd7bd8e87 data/models/siglip2-onnx/head.json \
      | sha256sum -c - \
      && sha256sum data/models/siglip2-onnx/siglip2_vision.onnx data/models/siglip2-onnx/head.json > data/models/siglip2-onnx.VERIFIED ; \
    else \
      echo "WARNING: data/models/siglip2-onnx 가 없어 SigLIP2 없이 빌드한다(사진 판별 불가, 서버 로그 photo model status=missing)"; \
    fi

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
