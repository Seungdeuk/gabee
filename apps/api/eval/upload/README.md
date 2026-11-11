# 업로드 단계 평가 (글자 읽기 + 개인정보 가리기)

가족이 올린 사진·PDF를 글로 읽는 단계(`app/shared/llm/doc_ai.py`)와 그 글에서 개인정보를 가리는 단계(`app/features/ai_assistant/ingest/llm_ingest.py` 의 `mask`)를 서비스 코드 그대로 불러 잰다.
서비스 코드는 고치지 않는다. 모델은 서비스 설정(`ingest_ocr_model`, `ingest_mask_model` 이 비면 `llm_model`)을 그대로 쓴다.

## 비용 규칙

- Anthropic API 키는 **평가 대상 서비스 호출**(`read_image`/`read_pdf`, `find_pii`)에만 쓴다. 비용은 응답의 실제 토큰 수 × 단가(Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50 per MTok)로 센다. 모르는 모델이면 멈춘다.
- 평가 문서 만들기는 `claude -p` 헤드리스(구독, `ANTHROPIC_API_KEY` 제외)로만 한다 (`common.headless`).
- `--max-usd` 는 필수. 누적 비용이 닿으면 새 쪽·문서를 시작하지 않고 멈춘다(이미 진행 중인 `--workers` 개 호출은 끝나므로 상한을 조금 넘을 수 있다). 쪽·문서마다 `runs/` 에 저장하고, 같은 `--name` 으로 다시 돌리면 끝난 것은 건너뛴다(실패한 것은 다시 한다). 모델·시드·표본이 다르면 이어 하기를 거부한다.
- 결과 JSON 에 모델명, 단가, 시드, 토큰, 비용이 남는다.

## 1. 글자 읽기 `ocr_eval.py`

```
cd apps/api
PYTHONPATH=. python eval/upload/ocr_eval.py --name sonnet_clean --max-usd 2 [--n 50] [--seed 7] [--set clean|degraded] [--input image|pdf]
PYTHONPATH=. python eval/upload/ocr_eval.py --name sonnet_clean --max-usd 2 --rescore   # 호출 없이 다시 채점
```

데이터는 `gabee_share/OCR_평가데이터_KDoc/` (공개 공공문서 100쪽, 정답 검증 항목, 이전 엔진 결과). 읽기만 하고 고치지 않는다. 채점은 그 폴더의 `score_ocr.py` 를 그대로 불러 쓴다.

- 표본: 문서 종류 4개(Manuals·Notices·Reports·Statistics)에서 같은 수씩, 시드 고정으로 뽑는다(기본 50쪽 = 13/13/12/12). `--set degraded` 는 흐림·기울임을 입힌 20장 중에서 뽑는다.
- 입력: `image` 는 `images/<set>/` 의 이미지를 서비스의 `ocr_image`(긴 변 1900px JPEG)로, `pdf` 는 쪽 PDF 를 `read_pdf` 로 읽는다.
- 지표(전부 코드로 계산)

| 지표 | 정의 |
|---|---|
| 문장 일치 엄격 / 문장부호 무시 / 느슨 | `score_ocr.py` 그대로 (정답 문장이 출력에 들어 있나) |
| 표 구조 / 칸 글자 읽기 | `score_ocr.py` 그대로 (칸 글자와 위·아래·좌·우 이웃 칸이 맞나 / 칸 글자만) |
| 표 구조 ÷ 칸 글자 | 글자는 읽었는데 구조가 깨진 정도(`table_struct_given_cell`) |
| 표 낸 쪽 비율 | 표 정답이 있는 쪽 중 출력에 표(마크다운·HTML)가 하나라도 있는 쪽 |
| 머리말·꼬리말 제거 | `score_ocr.py` 그대로 |
| CER(`cer_pct`) | 문자 오류율. 정답은 디지털 PDF 의 글자층. 글자층을 30자 안팎 조각으로 모아 각 조각이 읽은 글 어디에든 가장 가깝게 들어 있는 편집거리를 합쳐 정답 글자 수로 나눈다(읽는 순서 무시). 한글·숫자·영문만 비교(공백·표 기호·문장부호 제외), 머리말·꼬리말 정답은 뺀다 |
| CER 전체(`cer_global_pct`) | 쪽 전체를 한 줄로 맞춘 편집거리. 읽는 순서·표 읽는 방향이 글자층과 다르면 크게 나온다(참고용) |
| 날짜·금액·숫자 정확도 | 정답 글자층에서 뽑은 토큰(날짜 `YYYY.M.D`/`년월일`, 금액=쉼표로 묶였거나 `원`이 붙은 숫자, 그 밖의 숫자)이 읽은 글에 같은 개수만큼 있나(순서 무시, 천 단위 쉼표 무시). `number_extra_pct` 는 읽은 글에만 있는 숫자 비율 |
| 표시율 | `[판독불가]`·`[?]` 개수(천 자당)와 하나라도 있는 쪽 비율 |

- 비교표: 같은 쪽을 `reference_results/{rapidocr, claude_haiku, claude_sonnet}/<set>/` 의 이전 결과로 같은 지표로 다시 채점해 `compare_same_pages` 에 넣는다(API 호출 없음). 이전 결과 100쪽 전체의 요약은 `reference_results/results_ocr_이전실행.json` 에 있다. 주의: 이전 `claude_sonnet` 결과의 k080(통계표) 한 쪽이 빈 글이라 그 쪽의 숫자 약 1,800개가 모두 실패로 잡혀 Sonnet 의 숫자 정확도·CER 비교값이 낮게 나온다.
- 한계: KDoc 정답 항목은 공공문서(통계표·보고서·매뉴얼·공고) 기준이라 영수증·고지서 같은 가족 앱 문서보다 표가 훨씬 어렵다. 글자층은 사람이 만든 정답이 아니라 PDF 에 들어 있는 글자라서 머리말·각주·표 칸 순서가 읽는 순서와 다를 수 있다(그래서 CER 은 조각 단위로 순서를 무시한다). 흐린 사진은 컴퓨터로 만든 열화라 실제 폰 사진이 아니다. `photos/`(영수증·라벨·손글씨)는 정답이 없어 이 평가에 넣지 않았다. 공식 채점기(olmocr-bench)와 같은 규칙의 근사 구현이다. 실제 가족 사진은 쓰지 않는다.

## 2. 개인정보 가리기 `mask_eval.py`

```
cd apps/api
python eval/upload/mask_eval.py gen [--seed 11] [--force]                                  # 평가 문서 만들기(헤드리스, API 비용 없음)
PYTHONPATH=. python eval/upload/mask_eval.py run --name haiku_base --max-usd 0.5 [--limit 5] [--no-family] [--rescore]
```

- 문서 만들기: 헤드리스 Sonnet 이 문서 종류 40가지(병원·약국 영수증, 가정통신문, 택배, 이체 확인, 카드 내역, 임대차, 단톡방·문자 대화, 중고거래 채팅 등) 각각의 틀을 `[[NAME1]]`·`[[PHONE1]]` 같은 자리표시로만 쓴다. 값은 코드가 시드로 만든 **가짜 값**으로 채운다.
  - 주민번호: 형식만 맞고 검증 숫자가 틀린 값(실제 번호가 될 수 없음), 카드: `9999` 로 시작(발급사 없는 대역), 계좌: `000-` 로 시작, 전화: `010-555x-xxxx`, 주소: 실제 시·도 + 가짜 구·도로(`예시구 샘플로`), 이메일: `example.com`, 이름: 가상 성+이름 조합(가족 이름과 겹치지 않음).
  - 가상 가족 4명(한서진·오태윤·오지안·오하은)을 `family` 인자(`FamilyTagger`)로 넘긴다. 대화체 문서는 성을 뗀 이름(`지안이는`)도 심는다.
  - 가려야 할 값(이름·가족 이름·전화·주민번호·계좌·카드·주소·이메일·생년월일)과 지켜야 할 값(금액·날짜·상호·주문/접수 번호)을 정답으로 `data/mask_set.json` 에 저장하고 sha256 을 `data/mask_set.sha256` 에 적어 잠근다. `run` 은 해시가 다르면 멈춘다. `gen --force` 로 다시 만들 수 있지만 점수를 본 뒤 정답을 바꾸는 용도로 쓰지 않는다.
- 지표(전부 코드)

| 지표 | 정의 |
|---|---|
| 재현율 `recall_pct` | 심은 값 중 가린 글에 전혀 남지 않은 비율. 값이 통째로 남으면 `missed_full`, 이름의 이름 부분이나 주소의 도로명+번호처럼 일부만 남으면 `missed_partial`(재현율에서는 둘 다 놓침, `recall_lenient_pct` 는 일부 남음을 봐 준 값) |
| 종류별 재현율 | `by_type` (번호류는 구분 문자를 무시하고 숫자열로도 비교) |
| 과하게 가림 `overmask_pct` | 지켜야 할 값(금액·날짜·상호·주문번호)이 가린 글에서 사라진 비율. `overmask_by_type` 로 종류별. |
| 가족 이름 `family` | 가족 이름 값마다 글자가 사라지고 `[가족:<id>]` 로 바뀌었나(`tagged_ok`), 그대로 남았나(`left_raw`), 사라졌지만 가족 표시가 아니라 `[이름]` 등으로 갔나(`wrong_token`) |
| `extra_tokens_approx` | 가린 표시 수가 문서마다 심은 값 수보다 많은 만큼의 합(대략치. 같은 값이 여러 번 나오면 더 많아지는 것이 정상이라 참고용) |

- 한계: 문서는 모델이 쓴 가상 문서라 실제 가족 사진·스캔의 노이즈(OCR 오독)가 없다. 사람 이름은 가상 조합이라 실제 이름 분포와 다르다. 번호는 가짜 패턴이라 규칙 검출기의 검증(주민번호 검증 숫자 등)을 통과하지 못하는 것이 있어 그 번호는 사실상 Claude 의 판단으로만 가려진다(실제 번호에 대한 규칙 안전망 효과는 과소 평가될 수 있다). 지킬 값의 라벨은 모델이 정해서 `환자등록번호`처럼 개인 식별 성격이 있는 번호 라벨이 `ORDERNO` 에 섞일 수 있으니 `overmask_by_type` 은 종류별로 해석한다. 생일은 지킬 날짜가 아니라 가릴 값(`BIRTH`)으로 센다. 문서 40건·심은 값 약 190개라 종류별 수치(주민번호 9개 등)는 표본이 작다.

## 폴더

- `common.py` 비용·저장·헤드리스 도구, `ocr_eval.py`, `mask_eval.py`
- `data/` 잠근 평가 문서(가짜 데이터만), `runs/` 결과(`ocr_<이름>.json`, `mask_<이름>.json`; `*_pilot.json` 은 시범 실행)

## 3. 실제 문서 양식 + 가상 개인정보 이미지 `build_real_set.py` / `real_eval.py`

실제 한국 생활 문서 양식(법령 별지 서식)의 빈칸에 가상 값을 써 넣은 이미지(깨끗한 판 + 폰으로 찍은 듯한 사진판)로 **사진 읽기 → 개인정보 가리기** 를 서비스 경로 그대로 잰다. 데이터는 `gabee_share/upload_eval_real/`(git 에 넣지 않음).

```
cd apps/api
python eval/upload/build_real_set.py fetch                    # 법제처 서식 PDF 내려받기 + sources.json (이미 있으면 건너뜀)
python eval/upload/build_real_set.py build [--seed 20261110] [--force]   # 값 채우기 + 사진판 + truth.json + data.lock.json
PYTHONIOENCODING=utf8 PYTHONPATH=. python eval/upload/real_eval.py --name real_sonnet --max-usd 5 [--set clean|photo|both] [--limit 2] [--no-family] [--rescore]
```

- 양식: 국가법령정보센터 별표·서식 24종(진료비·약제비 영수증, 처방전, 진단서, 기부금영수증, 보험료·교육비 납입증명서, 근로소득 원천징수영수증, 국세·지방세 고지서, 전입신고서, 자동차 양도증명서, 요양비 청구서, 계좌 신고서 등). 법령의 서식은 저작권법 제7조(보호받지 못하는 저작물)라 자유 이용이며 출처 URL·시행일·받은 날짜는 `sources.json`. 라이선스가 불분명한 사이트(비즈폼 등)의 양식은 쓰지 않았다. 받은 PDF 는 실행하지 않고 pypdfium2 로 열기만 한다. 관리비 고지서·가정통신문처럼 공개 라이선스 서식을 못 찾은 종류는 넣지 못했다.
- 칸 찾기: PDF 에 그려진 표 선과 글자층으로 코드가 정한다(헤드리스·API 미사용). `real_specs.py` 가 양식마다 (칸 이름, 값 종류, 방향)을 적고, 칸을 못 찾거나 이미 글자가 있거나 값이 안 들어가면 건너뛴다. `truth.json` 에는 실제로 쓴 값만 들어간다(`fields` 에 칸 이름·그림 위치, `skipped` 에 건너뛴 칸과 사유).
- 값: 전부 가짜(`mask_eval.make_value` 와 같은 규칙: 전화 010-555x, 카드 9999 대역, 계좌 000-, 주민번호 검증 숫자 틀림, 이메일 example.com, 가상 주소). 가상 가족 4명(한서진·오태윤·오지안·오하은)이 각 양식 a 판의 주인공(환자·납세자 등)이고, 일부 문서의 상대방으로도 들어간다. 양식마다 a·b 두 판(값 다름), 판마다 clean(PNG)·photo(JPEG) 이미지.
- 사진판: 책상 위에서 비스듬히 찍은 것처럼 회전(±4도)·원근·그림자 띠·밝기 불균일·색 번짐·센서 노이즈·흐림·JPEG(품질 42~65, 긴 변 1600px). 시드 고정.
- 정답: `truth.json` 의 문서별 `pii`(가려야 할 값: NAME·FAMILY·RRN·PHONE·ADDR·EMAIL·CARD·ACCOUNT·BIRTH), `keep`(지켜야 할 값: AMOUNT·DATE·SHOP·ORDERNO), `ignored`(점수 제외: 사업자번호·업소 전화·업소 주소·등록번호·그냥 글자), `template_text`(양식 글자층), 가족 목록 `family`. `data.lock.json` 에 truth·sources·이미지·양식 PDF 의 sha256 을 잠그고 `real_eval.py` 가 시작할 때 확인한다(다르면 멈춤). 점수를 본 뒤 정답을 바꾸는 용도로 `--force` 를 쓰지 않는다.
- 러너: 서비스 `_from_image_llm` 과 같은 순서(`converters.prepare_image` → `llm_ingest.ocr_image` → `service._mask`)로 부른다. 서비스 코드는 고치지 않고 `doc_ai.find_pii` 만 감싸 가리기 토큰을 센다. 읽기·가리기 모델이 달라 단가를 따로 적용하고(모르는 모델이면 멈춤), `--max-usd` 는 필수다. 이미지마다 `runs/real_<이름>.json` 에 저장하고 같은 `--name` 으로 다시 돌리면 끝난 것은 건너뛴다(모델·데이터·family·세트·개수가 다르면 거부). 시범은 `--limit 2` 로 고르게 뽑은 2장(`real_pilot.json`).
- 지표(전부 코드): 읽기 정확도(값이 읽은 글에 있나; 금액=숫자 토큰, 날짜=연·월·일 순서, 번호=숫자열, 이름·상호·주소=공백 무시), 개인정보 재현율(`recall_pct`: 심은 값 전체 기준, `recall_given_read_pct`: 읽은 값만 기준, 종류별, 가족 이름은 `[가족:<id>]` 로 바뀌었는지 따로), 과하게 가림(읽은 지킬 값이 가린 글에서 사라진 비율), 참고로 양식 글자 재현율. clean·photo·all 로 나눠 낸다.
- 한계: 값을 쓴 칸이 양식당 3~10개라 종류별 표본이 작다(주민번호 32·전화 16·카드 6·계좌 6·생년월일 2 등). 값 글자는 칸 높이에 맞춰 작게 들어가 라벨보다 작은 곳이 있다(사진판에서 읽기 어려움이 커진다). 국세·지방세 고지서처럼 칸이 없는 양식은 값을 거의 못 넣었다. 사진판은 컴퓨터로 만든 열화라 실제 폰 사진과 다르다. 주민번호 등은 가짜 패턴이라 규칙 검출기를 통과하지 못하는 것이 있다(`mask_eval` 와 같은 한계).

### 정정: "과하게 가림 0%"와 사업장 주소 (4차 감사 반영)

- `overmask_pct`(과하게 가림)는 지킬 값(금액·날짜·상호·주문번호)만 센다. 채점에서 제외한 사업장 주소(`BADDR`)가 가려져도 이 값에는 잡히지 않았으므로 "과하게 가림 0%"는 사업장 주소를 뺀 값이었다. 별도 칸 `baddr_masked_n`(읽은 사업장 주소 `baddr_read_n` 중 가린 글에서 사라진 수)을 추가했다.
- 같은 96장·같은 읽은 글(`real_real_sonnet.json`)을 새 칸으로 다시 채점하면 주소 안전망 수정 전(`real_real_sonnet`)은 15장 중 0, 주소 안전망을 넣은 직후(`real_addrfix_haiku`)는 15장 중 15장이 가려졌다. 사업장 라벨 옆 주소를 건너뛰게 고친 뒤(`real_addrfix2_haiku`)는 0이다.
