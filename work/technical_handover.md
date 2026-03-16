# HLS Continuum Validator: 기술 아키텍처 및 알고리즘 핸드오버 (v1.8)

이 문서는 HLS 스트림의 A/V 동기화 및 연속성 분석 도구인 'HLS Continuum Validator'의 핵심 로직과 기술적 진화 과정을 정리한 것입니다. 다른 인공지능 모델이나 개발자가 프로젝트를 인계받아 분석할 수 있도록 상세히 설명합니다.

---

## 1. 프로젝트 개요
- **목표**: HLS 스트림의 세그먼트 간 A/V Offset 및 Jitter를 분석하여, 특히 **안드로이드 크롬(Android Chrome)** 환경에서 발생하는 재생 중단 현상을 사전 진단.
- **핵심 가설**: 절대적인 Offset 수치보다 **'수치의 규칙성(Predictability)'**과 **'진동(Oscillation)'** 패턴이 하드웨어 디코더 안정성에 더 큰 영향을 미침.

## 2. 주요 기술 스택
- **Frontend**: PyScript (Python inside Browser), mux.js (Segment Parsing), Chart.js (Visualization)
- **Engine**: Python 기반 통계 및 진단 엔진 (`js/base.py`)
- **Deployment**: Cloudflare Pages

---

## 3. 핵심 알고리즘 및 로직 (v1.8 기준)

### A. 동적 격자 감지 (Dynamic Grid Detection)
- **배경**: 오디오 샘플링 레이트(44.1kHz vs 48kHz)에 따라 FFmpeg의 `aresample`이 생성하는 최소 보정 단위(격자)가 다름 (예: 약 7.8ms, 15.6ms 등).
- **로직**: 분석 구간 내의 모든 지터(Jitter) 값 중 가장 빈번하게 발생하는 최빈값(Statistical Mode)을 추출하여 해당 스트림의 **'추정 격자(Estimated Grid)'**로 설정.
- **효과**: 환경에 구애받지 않고 '의도된 보정' 패턴을 스스로 학습하여 오판을 방지.

### B. 영점 교차율 (Zero-crossing Rate, ZCR) 분석 (v1.9 GAP 면역 체계)
- **배경**: 소스 자체의 불연속성(Gap) 발생 직후에는 오프셋이 일시적으로 요동칠 수 있으며, 이를 인코딩 결함인 '진동'으로 오판할 위험이 있음.
- **로직**:
  1. **v1.9 GAP Immunity**: GAP(`Discontinuity`)이 감지된 지점부터 이후 **3개 세그먼트**까지를 '회복 기간(Recovery Window)'으로 설정.
  2. 해당 회복 기간 내에서 발생하는 부호 전환(ZCR) 및 진폭 변화는 진동 분석 카운트에서 제외.
  3. 회복 기간 종료 후 스트림이 동적 격자 패턴 내로 복귀하면 `STABLE AFTER GAP` 판정.
- **효과**: 소스의 물리적 끊김과 소프트웨어적 인코딩 설정 오류를 완벽하게 분리 진단.

### C. 규칙성(Predictability) 및 복구력 분석
- **변화량의 변화량(Diff of Diff)**: 연속된 세그먼트 간 지터의 차이가 1.5ms 이내인 경우 '격자 정렬(Grid Aligned)' 상태로 판단.
- **GAP 복구력**: 타임라인 불연속(Gap) 발생 이후, 몇 개의 세그먼트 내에 다시 안정적인 격자 패턴으로 복구되는지 측정.

---

## 4. 버전별 주요 변경 이력

| 버전 | 주요 특징 | 핵심 변경 사항 |
|:---|:---|:---|
| **v1.1-1.3** | 기초 분석 | A/V Offset 계산 및 기본 그래프 렌더링 |
| **v1.4** | 지터 도입 | Jitter(변화량) 계산 및 `JAG` 배지 도입 |
| **v1.5** | 임계값 최적화 | Linear Drift와 Jitter를 구분 |
| **v1.6** | 지능형 엔진 | `Predictability` (규칙성) 기반 진단 도입 |
| **v1.7** | 감도 최적화 | 진폭 임계값을 30ms로 상향 (Grid Jitter 수용) |
| **v1.8** | ZCR & 동적 격자 | 영점 교차율(ZCR) 및 통계적 격자 추출 도입 |
| **v1.9** | **GAP 면역 체계** | GAP 이후 3개 세그먼트 면역 및 `STABLE AFTER GAP` 판정 도입 |

---

## 5. 진단 임계값 가이드 (Android Chrome 기준)
- **Synced**: Offset < 50ms 또는 규칙적인 격자 패턴 내 120ms 미만.
- **Consistent**: 동적 격자와 일치하는 규칙적인 보정 패턴 (정상).
- **Warning**: Offset > 120ms 또는 불규칙한 지터 40ms 초과.
- **Critical (Fatal)**: Offset > 200ms 또는 ZCR 기반 대형 진동(30ms+) 2회 이상 발생.

---

## 6. 추가 분석을 위한 팁
- `js/base.py`의 `all_raw_diffs` 리스트는 스트림의 오디오 보정 성향을 파악하는 데 가장 중요한 시계열 데이터입니다.
- 안드로이드 재생 실패 시, 항상 `ZCR-ZIG` 배지의 빈도와 `Estimated Grid`의 일관성을 먼저 확인하십시오.
