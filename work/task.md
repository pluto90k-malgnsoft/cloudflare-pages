# HLS Continuum Validator 개발 현황 (v2.0)

## 프로젝트 개요
안드로이드 크롬 및 저사양 디바이스에서의 HLS 재생 안정성을 보장하기 위한 고정밀 A/V 연속성 분석 도구.

## 현재 진행 상황

- [x] v1.6: 규칙성(Predictability) 기반 진단 도입
- [x] v1.7: 진동 감도 최적화 및 격자 지터 수용
- [x] v1.8: 영점 교차율(ZCR) 및 동적 격자 감지 도입
- [x] v1.9: GAP 면역 체계 및 동적 복구 판정 도입
- [x] v2.0: 타임라인 무결성(Monotonicity) 체크 강화
    - [x] PTS Backward Jump (시간 역행) 감지 로직 구현
    - [x] 타임라인 역행 시 최우선 `FATAL` 판정 도입
    - [x] 거대 GAP(10초 이상) 질적 진단 도입
    - [x] v2.0 업데이트 및 최종 배포 및 문서화
- [x] v2.1: Aresample(async=1) 적용 여부 감지 엔진 도입
    - [x] 세그먼트 간 오디오 연속성 Gap 분석 (Audio Continuity Gap)
    - [x] 오디오 실제 Duration vs 선언 Duration 편차 분석 (Duration Mismatch)
    - [x] 세그먼트 내 오디오 PTS 간격 표준편차 분석 (Intra-segment Regularity)
    - [x] 대시보드에 Aresample 판정 카드 추가 (적용됨/미적용 의심)
    - [x] 테이블에 A-Gap 컬럼 및 AUDIO-GAP, DUR-DRIFT 배지 추가
    - [x] Aresample 전용 진단 보고서 섹션 추가
    - [x] v2.1 문서화
- [x] 기술 핸드오버 문서 및 프로젝트 정리 (v1.9 기준 완료)

## 최종 결과
- **v1.9**: GAP 발생 후의 회복력을 측정하여 불필요한 경고를 줄임.
- **v2.0**: 시간의 흐름(방향성)을 먼저 검증하여 안드로이드 디코더 정지 원인을 100% 포착.
- **v2.1 (현재)**: FFmpeg `-af aresample=async=1` 옵션 적용 여부를 자동 감지하여 안드로이드 크롬 재생 불가 원인을 진단.
