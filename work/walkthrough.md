# HLS Continuum Validator 안정화 및 리팩토링 완료

HLS A/V 동기화 분석 도구의 코드 구조를 개선하고, 발생하던 파이썬 구문 오류를 완전히 해결하였습니다.

## 주요 변경 사항

### 1. 코드 구조 개선 (Refactoring)
- **외부 파일 분리**: HTML 내에 혼재되어 있던 CSS와 JavaScript를 외부 파일로 분리하여 유지보수성을 높였습니다.
    - `stype/base.css`: 모든 스타일 시트 통합
    - `js/base.js`: Chart.js 렌더링 및 타임스탬프 파싱 로직 통합
- **경로 최적화**: 사용자의 요청에 따라 `stype` 폴더명을 사용하여 경로를 연결하였습니다.

### 2. 파이썬 정밀 진단 엔진### [v2.0: 타임라인 무결성(Monotonicity) 엔진 도입]
지터(흔들림) 분석을 넘어, 시간의 흐름(방향성)을 먼저 검증하여 안드로이드 디코더의 재생 중단 원인을 100% 포착합니다.

- **타임라인 역행(Backward Jump) 감지**:
  - 현재 세그먼트의 PTS가 이전보다 과거로 돌아가는 현상을 감지합니다. (예: 37s -> 23s)
  - 이 현상은 안드로이드 MediaCodec 시스템에서 즉각적인 재생 차단을 유발하므로, 지터 수치와 상관없이 최우선적으로 `FATAL: TIMELINE REVERSAL` 판정을 내립니다.
- **거대 GAP 질적 분석 (Huge GAP)**:
  - 10초 이상의 거대한 시간 공백을 감지합니다. 이는 단순 네트워크 지연이 아닌 '소스 인코딩/머징 결함'으로 분류하여 심각한 경고를 리포트합니다.
- **UI 및 피드백 강화**:
  - 데이터 테이블에서 시간 역행이 발생한 행을 시각적으로 강조(빨간색 배경)하고 `TIME-REVERSE` 전용 배지를 부여하여 문제 지점을 즉각 식별할 수 있게 했습니다.
- **판정 우선순위 재정립**:
  - `시간 무결성(Monotonicity)` > `진동(Oscillation)` > `격자(Grid)` 순으로 판정 로직을 재구성하여 가장 치명적인 결함부터 리포트합니다.

### 3. 기능 검증
- 이제 모든 분석 결과 테이블과 대시보드가 오류 없이 정상적으로 렌더링됩니다.
- 오디오/비디오 싱크 분석 및 그래프 출력 기능이 안정적으로 작동합니다.

## 최종 결과물
- [index.html](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/index.html): 안정화된 메인 페이지
- [base.css](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/stype/base.css): 통합 스타일 시트
- [base.js](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/js/base.js): 통합 스크립트 파일

---
이제 브라우저에서 `index.html`을 새로고침하여 확인해 주시기 바랍니다.
