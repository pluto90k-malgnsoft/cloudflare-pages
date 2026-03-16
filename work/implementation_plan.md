# v2.0 타임라인 무결성(Timeline Monotonicity) 엔진 구현 계획

지터(흔들림)를 넘어 시간의 방향성(역행)을 검증하여 안드로이드 크롬의 '재생 불가' 원인을 100% 포착합니다.

## Proposed Changes

### [js/base.py] - 진단 엔진 고도화
- **Timeline Monotonicity Check**: 
  - 비디오/오디오의 시작 시간이 이전 세그먼트보다 과거인 경우(`curr_start < prev_start`)를 감지하는 로직 추가.
  - 이 경우 즉시 `FATAL: TIMELINE REVERSAL` 판정.
- **Qualitative GAP Analysis**:
  - GAP의 크기가 일정 임계값(예: 10초)을 초과하는 경우, 단순한 지연이 아닌 '소스 인코딩 결함'으로 분류하여 경고 강화.
- **Diagnostic Priority Update**:
  - 지터가 안정적이더라도 타임라인 역행이 발견되면 최우선적으로 `FATAL` 리포트를 생성하도록 판정 우선순위 조정.

### [index.html] - UI 업데이트
- 버전 명칭을 v2.0으로 상향 조정.
- 타임라인 역행 발생 시 시각적으로 명확한 경고(빨간색 배경 등) 추가 고려.

## Verification Plan

### Automated Tests
- 타임라인이 역행하는 샘플 로그 데이터(Index 6 -> 7 역행 케이스)를 입력하여 `FATAL: TIMELINE REVERSAL`이 정확히 리포트되는지 확인.
- 거대 GAP이 포함된 데이터를 입력하여 질적 분석 메시지가 올바르게 출력되는지 검증.

### Manual Verification
- 브라우저에서 v2.0 엔진이 작동하는지 최종 확인.
