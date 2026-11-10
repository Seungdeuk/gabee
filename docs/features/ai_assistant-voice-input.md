# 구현 현황: AI 채팅 음성 입력

- 상태: 진행 중 (코드·린트·앱 시험까지 확인, 실제 폰 확인은 새 빌드 뒤)
- 담당: 앱(mobile) AI 채팅
- 요구사항: docs/requirements/ai_assistant-voice-input.md

## 구현된 것

- 패키지 `expo-speech-recognition`(SDK 54 태그 `@sdk-54`, 3.1.3, MIT)을 추가하고 `app.json` 플러그인에 한국어 마이크 권한 문구를 넣었다. 팀 합의를 받은 의존성이다.
- `features/ai-assistant/hooks/useVoiceInput.js`: 권한 요청, 한국어(`ko-KR`) 인식 시작·중지, 중간 결과, 오류 안내(권한 거부·언어 미지원·일반 오류)를 한곳에 모았다. 네이티브 모듈이 없는 환경(Expo Go 등)에서는 import 로 화면이 죽지 않고 "음성 입력을 쓸 수 없어요" 안내만 띄운다.
- `AiAssistantScreen.js`: 마이크 막음(`MIC_ENABLED`)과 준비 중 안내 시트(`MicPendingSheet`, 삭제)를 없애고 실제 인식에 연결했다.
- `ChatInput.js`: 인식된 글자를 입력창에 채우고(앞서 쳐 둔 글자 뒤에 이어 붙임), 음성으로 받은 글이면 전송 때 `voice: true`로 표시한다. 폰 키보드 받아쓰기용 자동 포커스는 뺐다.
- `requiresOnDeviceRecognition`은 쓰지 않는다(폰 기본 인식 사용, 오디오는 앱이 저장·전송하지 않음).

## 남은 것

- 네이티브 모듈이라 **새 개발 빌드 또는 AAB**를 만들어야 실제 동작을 볼 수 있다. 실제 폰에서 한국어 인식·권한 거부·인식 중 닫기를 확인한다.
- Play 데이터 보안 양식과 개인정보 처리방침에 음성 입력(폰 음성 인식 서비스 사용) 문구를 추가한다.
- `AndroidManifest`의 안 쓰던 권한 정리 목록에서 `RECORD_AUDIO`는 이제 쓰이므로 뺀다(나머지 미사용 권한은 그대로).
