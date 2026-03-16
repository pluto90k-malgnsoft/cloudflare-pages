# Chromium DTS Sequence Analyzer 개발 기록

## 개요

`dts-analyzer.html` — Android Chrome에서 발생하는 `web_media_player_impl.cc:2068` 에러를 사전 검증하는 독립 분석기.
기존 HLS Continuum Validator(index.html)의 PES 레벨 분석 한계를 넘어 **AAC 프레임 레벨**까지 파싱하여 Chromium 내부 동작을 시뮬레이션한다.

---

## 대상 에러

```
FFmpegDemuxer: detected HLS manifest
Demuxing stream using ManifestDemuxer
ChunkDemuxer
Parsed buffers not in DTS sequence
RunSegmentParserLoop: stream parsing failed. append_window_start=0 append_window_end=inf
Error Group: PipelineStatus::DEMUXER_ERROR_COULD_NOT_OPEN
Error Code: 12
Stacktrace: third_party/blink/renderer/platform/media/web_media_player_impl.cc:2068
```

---

## Chromium 소스 분석 결과

### 에러 발생 체인 (소스 코드 확인 완료)

```
[1] ManifestDemuxer (manifest_demuxer.cc)
    → HLS manifest 감지, ChunkDemuxer에 위임
    → SetSequenceMode(true)  ← HLS는 sequence 모드

[2] ChunkDemuxer → MP2T StreamParser (mp2t_stream_parser.cc)
    → TS 패킷 파싱, ES 파서에 위임
    → EmitRemainingBuffers()로 전체 프레임을 한번에 전달

[3] ES Parser ADTS (es_parser_adts.cc)
    → AudioTimestampHelper로 AAC 프레임별 DTS 계산
    → PES DTS를 base로, 프레임마다 +1024/sampleRate 증분
    → audio_queue에 PES 도착 순서대로 push

[4] FrameProcessor::ProcessFrames (frame_processor.cc:385)
    → MergeBufferQueues(audio_queue, video_queue)
    → 실패 시: "Parsed buffers not in DTS sequence" → 재생 중단

[5] FrameProcessor::ProcessFrame (frame_processor.cc:962)
    → DTS 갭/역행 감지 시: Reset() + offset 보정 (에러 아님)
    → sequence mode에서는 자동 복구
```

### 핵심 발견 사항

| 항목 | 내용 |
|:---|:---|
| **유일한 치명적 에러** | `MergeBufferQueues()` 실패 (stream_parser.cc) |
| **DTS 할당 방식** | `AudioTimestampHelper`: PES PTS를 base로 리셋, 프레임마다 1024/SR 증분 |
| **DTS 갭 처리** | `ProcessFrame`에서 `Reset()` 후 재처리 (에러 아님, sequence mode) |
| **HLS 모드** | `SetSequenceMode(true)` — offset 자동 보정 |
| **버퍼 전달** | `EmitRemainingBuffers()`로 세그먼트 전체를 한번에 전달 |
| **타임라인 점프** | 큰 점프(>1s)는 Chromium이 내부적으로 배치 분리/리셋 처리 |

### AudioTimestampHelper 동작 (audio_timestamp_helper.cc)

```cpp
void SetBaseTimestamp(base::TimeDelta base_timestamp) {
    base_timestamp_ = base_timestamp;
    frame_count_ = 0;  // 리셋!
}

void AddFrames(int frame_count) {
    frame_count_ += frame_count;  // 1024씩 증가
}

base::TimeDelta GetTimestamp() {
    return base_timestamp_ + microseconds_per_frame_ * frame_count_;
}
```

→ 새 PES가 도착할 때마다 base 리셋, 이전 PES의 증분은 사라짐.

### MergeBufferQueues 실패 조건 (stream_parser.cc)

```cpp
for (size_t i = 0; i < num_itrs; ++i) {
    DecodeTimestamp ts = (*itrs[i])->GetDecodeTimestamp();
    if (last_decode_timestamp != kNoDecodeTimestamp && ts < last_decode_timestamp)
        return false;  // 모든 큐의 현재 head를 검사
}
```

→ 어떤 큐의 head든 last보다 작으면 즉시 실패.

---

## 실제 에러 원인 (비정상 소스 분석)

### 문제 패턴: PES 간격이 AAC 프레임 duration보다 좁음

```
PES #1: DTS = 1.443s → AAC 프레임 8개 생성 → 마지막 프레임 DTS ≈ 1.629s
PES #2: DTS = 1.629s → base 리셋 → 첫 프레임 DTS = 1.629s (OK, 연속)
PES #3: DTS = 1.633s → base 리셋 → 첫 프레임 DTS = 1.633s
         하지만 PES #2의 마지막 프레임 DTS = 1.652s (1.629 + 23.2ms)
         1.633 < 1.652 → DTS 역행! → MergeBufferQueues FAIL
```

AAC 프레임 duration (23.2ms) > PES 간격 (4ms) → 이전 PES에서 계산된 프레임 DTS가 다음 PES의 base보다 커서 역행 발생.

### 정상 소스와의 차이

| | 정상 소스 | 비정상 소스 |
|:---|:---|:---|
| **PES 간격** | ~163ms (7 AAC 프레임 분량) | 4ms (AAC 프레임보다 작음) |
| **타임라인 점프** | 46s→23s (콘텐츠 경계, >1s) | 1.652s→1.633s (미세 역행, 19ms) |
| **Chromium 처리** | 배치 분리/Reset → 정상 재생 | MergeBufferQueues FAIL → 재생 중단 |

---

## 분석기 버전 히스토리

### v1.0 (초기)
- AAC 프레임 레벨 DTS 파싱 (ADTS sync word 0xFFF)
- 프레임별 DTS 계산: `PES_DTS + (n * 1024 / sampleRate) * 90000`
- MergeBufferQueues 시뮬레이션
- 전체 DTS 타임라인 차트

### v1.1
- `#EXT-X-DISCONTINUITY` 태그 파싱
- Discontinuity 경계에서 inter-segment 검증 리셋

### v1.2
- Chromium `ProcessFrame` DTS 갭 검증 추가 (`delta > 2 * frame_duration`)
- DTS 갭 위반 카운트 및 대시보드 표시

### v1.3
- **치명적 버그 수정**: 프레임 정렬(sort) 제거
- Chromium은 PES 도착 순서대로 처리하므로, 정렬하면 역행을 감지 불가
- Chromium 소스 (`es_parser_adts.cc`, `stream_parser.cc`, `frame_processor.cc`) 확인

### v1.4
- PES 배치 단위 MergeBufferQueues (잘못된 접근 — 이후 v1.5에서 수정)

### v1.5
- `mp2t_stream_parser.cc` 확인: `EmitRemainingBuffers()`가 세그먼트 전체를 한번에 전달
- 세그먼트 전체 MergeBufferQueues로 복원
- Gap을 informational로 변경 (sequence mode에서 에러 아님)
- PES DTS 순서 디버그 로그 추가

### v1.6 (현재)
- **타임라인 점프 vs 미세 역행 구분**
- 큰 DTS 역행(>1s): 콘텐츠 경계 → Chromium 내부 처리 → PASS
- 작은 DTS 역행(<1s): 인코딩 결함 → MergeBufferQueues FAIL → FAIL
- `splitByTimeline()`: 프레임을 연속 구간으로 분할, 구간별 MergeBufferQueues 실행

---

## 분석기 구조

### 파싱 파이프라인

```
TS Segment (188-byte packets)
  → PAT/PMT 파싱 → PID 식별 (Audio/Video)
  → PES 재조립 (TS 패킷 → 완전한 PES payload)
  → Audio PES: ADTS 파싱 (0xFFF sync) → 개별 AAC 프레임
  → 프레임별 DTS 계산 (AudioTimestampHelper 시뮬레이션)
  → Video PES: 각 PES = 1 video frame
```

### 검증 항목

| 검증 | 대상 | 판정 |
|:---|:---|:---|
| **Intra** | 연속 구간 내 트랙별 DTS 단조 증가 | FAIL = 치명적 |
| **Merge** | 연속 구간 내 A/V DTS 병합 단조 증가 | FAIL = 치명적 |
| **Gap** | 프레임 간 DTS 간격 > 2x frame_duration | 경고 (sequence mode 자동 처리) |
| **Inter** | 세그먼트 간 DTS 연속성 (같은 타임라인) | FAIL = 치명적 |

### 참조된 Chromium 소스 파일

| 파일 | 역할 |
|:---|:---|
| `media/formats/mp2t/es_parser_adts.cc` | AAC 프레임 파싱, AudioTimestampHelper로 DTS 할당 |
| `media/base/audio_timestamp_helper.cc` | PES PTS를 base로 프레임별 DTS 계산 |
| `media/base/stream_parser.cc` | `MergeBufferQueues()` — A/V DTS 병합 검증 |
| `media/filters/frame_processor.cc` | `ProcessFrames()` (에러 출력), `ProcessFrame()` (갭 처리) |
| `media/formats/mp2t/mp2t_stream_parser.cc` | TS 파싱, `EmitRemainingBuffers()` |
| `media/filters/hls_manifest_demuxer_engine.cc` | `SetSequenceMode(true)` |
| `media/filters/manifest_demuxer.cc` | ManifestDemuxer → ChunkDemuxer 위임 |

---

## 테스트 소스

| URL | 상태 | 특징 |
|:---|:---|:---|
| `pluto90k.v4.wecandeotest.com/.../V22133.m3u8` | 정상 재생 | 콘텐츠 경계(23s 점프) 있으나 미세 역행 없음 |
| `kcaqma2025.v4.wecandeo.com/.../V106323.m3u8` | 재생 실패 | Seg 0에서 19ms DTS 역행 (PES 간격 < AAC duration) |
