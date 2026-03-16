# HLS 분석 결과 시각화 및 분석 구간 설정 기능 강화 계획

분석 결과를 시각화하는 기능에 더해, 사용자가 원하는 특정 범위의 세그먼트만 집중적으로 분석할 수 있는 구간 설정 기능을 추가합니다.

## 제안된 변경 사항

### [기능 강화: 분석 구간 설정]
- **시작 인덱스 설정**: 분석을 시작할 세그먼트 번호(Start Index)를 입력받습니다.
- **분석 개수 설정**: 시작 지점부터 몇 개의 세그먼트를 분석할지 지정합니다.
- **유연한 탐색**: 전체 스트림 중 문제가 의심되는 중간 지점(예: 50번째 세그먼트부터 10개)만 빠르게 확인할 수 있습니다.

### [v1.8: 영점 교차율(ZCR) 및 동적 격자 분석 도입]
부호 전환 빈도와 샘플링 레이트를 연동하여 진단 엔진의 지능을 한 단계 더 높입니다.

#### [MODIFY] [js/base.py](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/js/base.py)
- **영점 교차율(Zero-crossing Rate) 분석**: 
  - 오프셋의 부호(+/-)가 바뀌는 빈도를 측정.
  - 교차 시의 진폭(Amplitude) 변화가 일정하면 'GRID_CORRECTION'으로, 불규칙하게 튀면 'FATAL_OSCILLATION'으로 분류.
- **동적 격자 감지 (Dynamic Grid Detection)**:
  - 44.1kHz vs 48kHz 등 샘플링 레이트에 따른 최소 보정 단위(Grid)를 통계적으로 추출.
  - 7.8ms와 같은 고정 주기가 아닌, 실제 데이터에서 우세하게 나타나는 '최빈 지터값'을 격자 기준으로 설정.
- **ZCR 기반 위험도 가중치**: 부호 전환이 잦을수록 디코더 버퍼에 가해지는 스트레스를 수치화하여 진단 결과에 반영.

#### [MODIFY] [index.html](file:///Users/jooyoungkim/Develop/wecandeo/cloudflare-pages/index.html)
- 버전 표기를 `v1.8`로 업데이트.

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

### Automated Tests
- N/A (Manual Verification Required in Browser)

### 수동 검증
1. 시작 세그먼트를 0이 아닌 값(예: 2)으로 설정했을 때, 실제 분석 로그와 테이블에 2번 세그먼트부터 출력되는지 확인.
2. 입력한 분석 개수만큼만 세그먼트가 처리되는지 확인.
3. 범위를 벗어난 입력(예: 전체 개수보다 큰 시작 번호)에 대한 예외 처리가 작동하는지 확인.
