# 운영 담당자용 명령 모음 — R11 교체 전 확인 (읽기 전용 위주)

2026-11-23. 대상(이전 준비 자료 기준): Cloud Run `gabee` / 프로젝트 `gabee-512904` / 리전 `asia-northeast3`. **이 문서의 명령은 담당자가 Cloud Shell 에서 실행한다. 저는 운영에 접속하지 않았다.** `describe` 를 `--format` 없이 통째로 출력·공유하지 않는다(환경변수·시크릿 참조가 보인다). 값은 아래 요약 파일에만 남긴다.

## 1. 읽기 전용 수집 (S4-1, S4-2, S4-6, S2b 조건)
```bash
P=gabee-512904; R=asia-northeast3; S=gabee
# (a) NER 환경변수만 추려서 저장(다른 환경변수·시크릿은 파일에 넣지 않는다)  -> S4-2
gcloud run services describe $S --project $P --region $R --format=json \
 | jq '{spec:{template:{spec:{containers:[{env:[.spec.template.spec.containers[0].env[]?|select(.name|startswith("PRIVACY_NER_"))]}]}}}}' > ner_env.json
# (b) 자원·동시성(S4-6/S2b 조건)
gcloud run services describe $S --project $P --region $R --format=json \
 | jq '{cpu_mem_limits:.spec.template.spec.containers[0].resources.limits, containerConcurrency:.spec.template.spec.containerConcurrency, scaling_and_cpu_annotations:(.spec.template.metadata.annotations|with_entries(select(.key|test("scale|cpu|boost|execution"))))}'
# (c) 현재 이미지 URI 와 최근 리비전(롤백 대상 확인)
gcloud run services describe $S --project $P --region $R --format="value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"
gcloud run revisions list --service $S --project $P --region $R --limit 10
```
```bash
# (d) 현재 운영 이미지 안 S0 해시·모드·ONNX Runtime 버전(S4-1, S4-6). <IMAGE> 는 (c)에서 얻은 값
docker run --rm --entrypoint sh <IMAGE> -c 'sha256sum /srv/data/models/ner-koelectra-small-v2b/model.onnx; python -c "import onnxruntime;print(onnxruntime.__version__)"'
docker run --rm --entrypoint python <IMAGE> -c "import json;from app.shared.privacy import ner;print(json.dumps(ner.ner_status()))"
```
기대: 해시 `46210943c45f01b6a9fa500894fb9821b1c130be63de8d8f7ef603d2d87ccf8e`. 스레드·동시성은 환경변수 `PRIVACY_NER_THREADS`·`PRIVACY_NER_MAX_CONCURRENCY`(없으면 기본 2/2)이며 (a)를 `jq` 필터에서 이름만 바꿔 확인한다.

## 2. 배포 전 게이트 (읽기 전용, 모드가 `required` 가 아니면 중단)
```bash
# 새 이미지의 실제 상태 저장
docker run --rm --entrypoint python <NEW_IMAGE> -c "import json;from app.shared.privacy import ner;print(json.dumps(ner.ner_status()))" > image_status.json
# 새 리비전(또는 업데이트 후) 설정과 함께 판정: 종료 코드 0 이어야 한다
python apps/api/scripts/check_ner_deploy_mode.py --service-json ner_env.json --image-status-json image_status.json
```
`auto`·`off`·오타·빈 값·비밀 참조, 옛 모델 폴더 덮어쓰기, 지문 ≠ `3831601b7ffb` 이면 종료 코드 1 이다. 종료 코드가 0 이 아니면 배포하지 않는다.

## 3. 새 리비전 만들기 (승인 후에만, 트래픽 0%)
```bash
gcloud run deploy $S --image <NEW_IMAGE> --project $P --region $R --no-traffic --tag candidate \
  --update-env-vars PRIVACY_NER_MODE=required
```
`--set-env-vars` 는 기존 환경변수를 전부 바꾸므로 쓰지 않는다. 이어서 candidate 리비전 설정으로 2절 게이트를 다시 돌리고, 통과한 뒤에만 트래픽을 옮긴다(이전 리비전 보존, 롤백은 `update-traffic --to-revisions <이전>=100`).

## 4. 회신할 표
| 항목 | 값 |
|---|---|
| 운영 S0 model.onnx SHA256 / 지문 | |
| 운영 `PRIVACY_NER_MODE`(환경변수 값, 없으면 "없음") | |
| CPU·메모리 제한, 동시성, 최소/최대 인스턴스, CPU 상시 할당 여부 | |
| `PRIVACY_NER_THREADS`·`PRIVACY_NER_MAX_CONCURRENCY` | |
| 운영 이미지 ONNX Runtime 버전 | |
| 롤백 대상 리비전 이름 | |
이 값을 받으면 `ops_replace/s2b_container.sh <라벨> <CPUS> <MEM> <THREADS> <CONCURRENCY>` 로 같은 조건에서 S0·R11 을 교차 측정한다.
