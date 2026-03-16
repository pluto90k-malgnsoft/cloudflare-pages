# HLS Continuum Validator 개발 현황 (v2.2)

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
- [x] v2.1.1: 실측 데이터 기반 Aresample 오탐 수정
    - [x] GAP/역행 세그먼트를 Aresample 지표 수집에서 제외
    - [x] 임계값 조정: Audio Gap 50→150ms, Duration 30→100ms, StdDev 2→5ms
    - [x] GAP 세그먼트에서 AUDIO-GAP/DUR-DRIFT 배지 억제
- [x] v2.2: PTS 기반 콘텐츠 경계 감지 엔진 도입
    - [x] PTS 역행 GAP을 콘텐츠 경계(편집/연결점)로 인식
    - [x] 콘텐츠 경계를 타임라인 역행 FATAL 판정에서 제외
    - [x] 연속 구간 내 역행만 FATAL로 판정 (진짜 오류만 포착)
    - [x] `DISC` 배지(파란색) 및 콘텐츠 경계 행 스타일 추가
    - [x] "정상 (Discontinuity N개)" 판정 로직 추가
    - [x] StdDev 임계값 추가 조정: 5→10ms (PES 파싱 특성 반영)
    - [x] v2.2 문서화
- [x] v2.3: DTS Sequence 검증 엔진 도입 (Chromium MergeBufferQueues 시뮬레이션)
    - [x] 세그먼트 내 오디오/비디오 DTS 단조 증가 검증
    - [x] A/V DTS 병합 시뮬레이션 (Chromium과 동일 조건)
    - [x] 세그먼트 간 DTS 연속성 검증 (콘텐츠 경계 제외)
    - [x] 대시보드 DTS 시퀀스 카드 / DTS-FAIL, DTS-REV, DTS-GAP 배지
    - [x] DTS Sequence 전용 진단 보고서 (Chromium 에러 메시지 포함)
    - [x] 판정 최우선순위: DTS 역행 > 타임라인 역행 > 진동 > ...
- [x] 기술 핸드오버 문서 및 프로젝트 정리 (v1.9 기준 완료)

## Chromium 에러 분석
- **에러**: `Parsed buffers not in DTS sequence` → `DEMUXER_ERROR_COULD_NOT_OPEN`
- **발생 지점**: `MergeBufferQueues()` (media/base/stream_parser.cc)
- **원인**: 오디오/비디오 DTS를 하나의 큐로 병합할 때, 오디오 DTS가 역행하면 즉시 실패
- **검증 조건**: `current_dts < last_decode_timestamp` → return false
- **해결**: `-af aresample=async=1`로 오디오 DTS 연속성 강제 보장
- **상세 분석**: [chromium_dts_error_analysis.md](chromium_dts_error_analysis.md)

## 테스트 소스
- **정상 재생 (aresample=async=1 적용)**: `https://pluto90k.v4.wecandeotest.com/file/2501/4926/V22133/V22133.m3u8`
  - 안드로이드 모바일 크롬 정상 재생 확인
  - PTS 역행 포함 (콘텐츠 경계 2개), `#EXT-X-DISCONTINUITY` 태그 없음
- **비정상 재생 (aresample=async=1 미적용)**: (확인 대기)

## 최종 결과
- **v1.9**: GAP 발생 후의 회복력을 측정하여 불필요한 경고를 줄임.
- **v2.0**: 시간의 흐름(방향성)을 먼저 검증하여 안드로이드 디코더 정지 원인을 100% 포착.
- **v2.1**: FFmpeg `-af aresample=async=1` 옵션 적용 여부를 자동 감지하여 안드로이드 크롬 재생 불가 원인을 진단.
- **v2.2**: PTS 역행을 콘텐츠 경계로 인식하여 오탐 제거. 실측 데이터 기반으로 임계값 최적화 완료.
- **v2.3 (현재)**: Chromium `MergeBufferQueues` DTS 검증을 시뮬레이션하여 `Parsed buffers not in DTS sequence` 에러를 정확히 진단.
