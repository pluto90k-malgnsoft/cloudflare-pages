# Chromium "Parsed buffers not in DTS sequence" 에러 분석

## 에러 메시지 전문
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

## 1. 에러 발생 체인 (Chromium 소스 코드 기반)

```
[1] WebMediaPlayerImpl (web_media_player_impl.cc:2068)
     ↓ HLS manifest 감지 → ManifestDemuxer 사용
[2] ManifestDemuxer → 내부적으로 ChunkDemuxer 위임
     ↓ TS 세그먼트 파싱 시작
[3] SourceBufferState::RunSegmentParserLoop()
     ↓ 파싱된 버퍼를 FrameProcessor에 전달
[4] FrameProcessor::ProcessFrames()
     ↓ MergeBufferQueues() 호출
[5] ★ MergeBufferQueues() → DTS 순서 검증 실패 ★
     ↓ return false
[6] "Parsed buffers not in DTS sequence" 로그 출력
     ↓ 파싱 중단
[7] DEMUXER_ERROR_COULD_NOT_OPEN → 재생 실패
```

---

## 2. 핵심 원인 코드 (Chromium 소스)

### MergeBufferQueues — DTS 순서 검증 (stream_parser.cc)

```cpp
// media/base/stream_parser.cc
bool MergeBufferQueues(
    const StreamParser::BufferQueueMap& buffers,
    StreamParser::BufferQueue* merged_buffers) {

  // ...병합 루프...

  if (last_decode_timestamp != kNoDecodeTimestamp &&
      ts < last_decode_timestamp)
    return false;  // ← 여기서 실패!

  // ...
}
```

**실패 조건**: 현재 버퍼의 DTS(Decode Timestamp)가 이전 버퍼의 DTS보다 **작으면** 즉시 `false` 반환.

### ProcessFrames — MergeBufferQueues 호출부 (frame_processor.cc)

```cpp
// media/filters/frame_processor.cc
bool FrameProcessor::ProcessFrames(...) {
  StreamParser::BufferQueue frames;

  if (!MergeBufferQueues(buffer_queue_map, &frames)) {
    MEDIA_LOG(ERROR, media_log_) << "Parsed buffers not in DTS sequence";
    return false;  // ← 이 에러 메시지가 출력됨
  }
  // ...
}
```

### ProcessFrame — DTS 불연속 감지 (frame_processor.cc)

```cpp
// 개별 프레임 처리 시 추가 검증
DecodeTimestamp track_last_decode_timestamp =
    track_buffer->last_decode_timestamp();

if (track_last_decode_timestamp != kNoDecodeTimestamp) {
  base::TimeDelta track_dts_delta =
      decode_timestamp - track_last_decode_timestamp;

  // 두 가지 실패 조건:
  // 1. DTS가 역행 (음수 delta)
  // 2. DTS 간격이 이전 프레임 duration의 2배 초과
  if (track_dts_delta.is_negative() ||
      track_dts_delta > 2 * track_buffer->last_frame_duration()) {
    // 불연속 처리 → Reset() 호출
  }
}
```

---

## 3. 기술적 분석

### DTS vs PTS 차이
| 항목 | PTS (Presentation TS) | DTS (Decode TS) |
|:---|:---|:---|
| 용도 | 화면에 보여줄 시간 | 디코더에 넣는 순서 |
| B-프레임 없을 때 | PTS = DTS | PTS = DTS |
| B-프레임 있을 때 | PTS ≠ DTS (PTS가 더 클 수 있음) | DTS < PTS |
| **Chromium 검증** | 검증 안 함 | **엄격히 검증** |

### 왜 DTS 순서가 깨지는가?

1. **오디오 인코더의 타임스탬프 생성**:
   - FFmpeg에서 `-af aresample=async=1` 없이 인코딩하면 오디오 프레임의 DTS가 소스의 원본 타임스탬프를 그대로 사용
   - 소스에 갭이나 겹침이 있으면 DTS도 불규칙해짐

2. **멀티트랙 병합 시 DTS 역행**:
   - `MergeBufferQueues()`는 오디오와 비디오 버퍼를 DTS 순서로 **하나의 큐에 병합**
   - 오디오 DTS가 비디오 DTS 대비 역행하면 병합 실패
   - 예: Video DTS=10.5s 다음에 Audio DTS=10.3s → **실패**

3. **`-af aresample=async=1`이 해결하는 이유**:
   - 오디오 타임스탬프를 강제로 연속화
   - 갭 → 무음 삽입, 겹침 → 트리밍
   - 결과적으로 오디오 DTS가 항상 단조 증가
   - 비디오 DTS와 병합 시에도 순서 보장

### 에러가 `append_window_start=0, append_window_end=inf` 인 이유
- 전체 미디어 범위를 처리 중 (윈도우 제한 없음)
- 세그먼트의 첫 부분부터 DTS 역행이 발생

---

## 4. HLS Continuum Validator와의 관계

### 현재 분석기의 한계
- 현재 PTS 기반 분석 → DTS 역행은 감지 불가
- Chromium은 PTS가 아닌 **DTS**를 검증하므로, 정확한 진단을 위해 DTS 분석이 필요

### 분석기 개선 방향
1. **DTS 시퀀스 검증 추가**: 세그먼트 내/간 DTS 단조 증가 확인
2. **멀티트랙 DTS 병합 시뮬레이션**: 오디오/비디오 DTS를 병합하여 역행 지점 감지
3. **Chromium과 동일한 검증 조건 적용**:
   - `current_dts < last_dts` → FATAL
   - `dts_delta > 2 * last_frame_duration` → WARNING

---

## 5. 결론

| 항목 | 설명 |
|:---|:---|
| **근본 원인** | 오디오 DTS가 단조 증가하지 않음 |
| **실패 지점** | `MergeBufferQueues()` — 오디오/비디오 DTS 병합 시 순서 역행 감지 |
| **해결책** | FFmpeg `-af aresample=async=1` 옵션으로 오디오 DTS 연속성 보장 |
| **데스크톱 vs 모바일** | 데스크톱 크롬은 더 관대, 안드로이드 크롬은 ManifestDemuxer→ChunkDemuxer 경로로 엄격 검증 |

### 참조 소스 코드
- `media/base/stream_parser.cc` — `MergeBufferQueues()` DTS 검증
- `media/filters/frame_processor.cc` — `ProcessFrames()` 에러 로그 출력
- `media/filters/source_buffer_state.cc` — `RunSegmentParserLoop()` 파싱 루프
- `third_party/blink/renderer/platform/media/web_media_player_impl.cc` — 에러 전파
