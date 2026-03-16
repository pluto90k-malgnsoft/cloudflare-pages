# HLS 분석 결과 시각화 및 분석 구간 설정 기능 강화 계획

분석 결과를 시각화하는 기능에 더해, 사용자가 원하는 특정 범위의 세그먼트만 집중적으로 분석할 수 있는 구간 설정 기능을 추가합니다.

## 제안된 변경 사항

### [기능 강화: 분석 구간 설정]
- **시작 인덱스 설정**: 분석을 시작할 세그먼트 번호(Start Index)를 입력받습니다.
- **분석 개수 설정**: 시작 지점부터 몇 개의 세그먼트를 분석할지 지정합니다.
- **유연한 탐색**: 전체 스트림 중 문제가 의심되는 중간 지점(예: 50번째 세그먼트부터 10개)만 빠르게 확인할 수 있습니다.

### [v1.9: GAP 연동형 ZCR 정밀화 및 오판 해결]
GAP(불연속) 발생 시 나타나는 급격한 오프셋 변화를 '진동'으로 오판하는 문제를 해결합니다.

#### [MODIFY] [js/base.py](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/js/base.py)
- **GAP 인식 ZCR 로직**:
  - 현재 또는 이전 세그먼트에 GAP이 있는 경우, 해당 구간의 부호 전환(ZCR)을 진동 분석에서 제외.
  - 순수하게 연속된 스트림(Continuous Stream) 내에서 발생하는 진동만 판정.
- **스마트 진단 고도화**:
  - GAP으로 인한 오차와 인코딩 옵션 미비(Oscillation)로 인한 오차를 명확히 분리하여 설명.
- **Badge 명칭 개선**: `ZCR-ZIG` 배지가 GAP 구간에는 표시되지 않도록 수정.

#### [MODIFY] [index.html](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/index.html)
- 버전 표기를 `v1.9`로 업데이트.

### [v1.7: 지능형 진동 분석 고도화 및 격자 지터 지원]
소규모 교정용 진동(aresample 등)이 '위험'으로 오판되는 문제를 해결하고, 실제 재생 중단을 유발하는 '거대 진동'을 선별합니다.

#### [MODIFY] [js/base.py](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/js/base.py)
- **진동 판정 임계값 상향**: `ZIGZAG` 및 `FATAL` 판정을 위한 진폭 기준을 기존 10ms에서 **30ms 이상**으로 상향 조정.
- **격자 지터(Grid Jitter) 인식**: 7.8ms, 15.6ms 등 특정 격자 단위의 지터가 반복되는 경우 'STABLE_CORRECTION'으로 분류하여 통과.
- **연속성 기반 진동 분석**: 진동이 짧은 구간에 집중적으로 발생하는지(Bursty) 아니면 듬성듬성 발생하는지 구분.
- **스마트 진단 리포트**: '위험' 대신 '정상 교정' 혹은 '주의' 등으로 상태를 더욱 세분화하여 표현.

#### [MODIFY] [index.html](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/index.html)
- 버전 표기를 `v1.7`로 업데이트.

## 검증 계획

### 수동 검증
1. 시작 세그먼트를 0이 아닌 값(예: 2)으로 설정했을 때, 실제 분석 로그와 테이블에 2번 세그먼트부터 출력되는지 확인.
2. 입력한 분석 개수만큼만 세그먼트가 처리되는지 확인.
3. 범위를 벗어난 입력(예: 전체 개수보다 큰 시작 번호)에 대한 예외 처리가 작동하는지 확인.
