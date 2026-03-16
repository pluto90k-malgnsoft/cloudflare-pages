# HLS Continuum Validator (PyScript)

PyScript와 mux.js를 이용한 브라우저 기반 고정밀 HLS 연속성 및 A/V 싱크 분석 도구입니다.

## 주요 기능

### 1. 고정밀 타임스탬프 분석
- MPEG-TS 및 fMP4 세그먼트의 PTS(Presentation Time Stamp) 및 DTS(Decoding Time Stamp)를 직접 파싱하여 분석합니다.
- 비디오와 오디오 스트림을 개별적으로 추출하여 각각의 시간 정보를 제공합니다.

### 2. A/V 싱크 및 Offset 진단
- **A/V Offset 계산**: 비디오와 오디오의 시작 PTS 간격(Skew)을 실시간으로 계산합니다.
- **FFMPEG 옵션 감지**: `-async 1` 또는 `aresample=async=1` 옵션 적용 여부를 Offset의 정밀도와 변동폭(Jitter)을 통해 추정합니다.
- **Android/Mobile 최적화**: Android Chrome 환경에서 발생할 수 있는 재생 실패 위험(Skew > 100ms)을 사전에 감지하고 경고합니다.

### 3. 연속성(Continuity) 체크
- 세그먼트 간의 시간 갭(Gap) 또는 겹침(Overlap)을 탐지하여 재생 중 끊김이나 튐 현상을 진단합니다.

## 사용 방법
1. 분석할 HLS(.m3u8) 주소를 입력합니다.
2. 필요시 CORS 이슈 해결을 위한 프록시 URL을 입력합니다.
3. '분석 시작' 버튼을 클릭하여 결과를 확인합니다.

---
*Created by Antigravity AI Agent*
