import asyncio
import m3u8
import urllib.parse
from js import window, document, Uint8Array
from pyodide.http import pyfetch

def log(msg, type=None):
    window.addLog(msg, type)

async def start_analysis(event):
    btn = document.getElementById("btn-run")
    btn.disabled = True
    document.getElementById("loader").style.display = "inline-block"
    document.getElementById("status-text").innerText = "분석 시작 중..."
    document.getElementById("progress-container").style.display = "block"
    document.getElementById("log-content").innerHTML = ""
    document.getElementById("summary-dashboard").innerHTML = ""
    window.updateProgress(0)

    url = document.getElementById("m3u8-url").value
    if not url:
        log("HLS URL을 입력해 주세요.", "error")
        reset_ui()
        return

    start_seg = int(document.getElementById("start-seg").value)
    max_segs = int(document.getElementById("max-segs").value)
    proxy_prefix = document.getElementById("proxy-prefix").value.strip()

    try:
        await check_hls_continuity(url, start_seg, max_segs, proxy_prefix)
    except Exception as e:
        log('분석 중 치명적 오류: ' + str(e), 'error')
    finally:
        reset_ui()

def reset_ui():
    document.getElementById("btn-run").disabled = False
    document.getElementById("loader").style.display = "none"
    document.getElementById("status-text").innerText = "완료"

def wrap_proxy(url, prefix):
    if not prefix:
        return url
    
    # 만약 prefix 끝에 url 파라미터가 명시되어 있다면 인코딩해서 붙임 (예: ?url=)
    if prefix.endswith("="):
        return prefix + urllib.parse.quote(url)
    
    # 그 외에는 그냥 단순 문자열 합치기 (예: https://proxy.com/)
    return prefix + url

async def fetch_with_proxy(url, prefix):
    final_url = wrap_proxy(url, prefix)
    try:
        res = await pyfetch(final_url)
        if res.ok: return res
        raise Exception('HTTP ' + str(res.status))
    except Exception as e:
        raise Exception('네트워크/CORS 오류: ' + str(final_url[:60]) + '... (' + str(e) + ')')

async def check_hls_continuity(m3u8_url, start_index, max_segments, proxy_prefix):
    log('[*] 분석 시작: ' + m3u8_url, 'header')
    
    try:
        resp = await fetch_with_proxy(m3u8_url, proxy_prefix)
        content = await resp.string()
        playlist = m3u8.loads(content, uri=m3u8_url)
    except Exception as e:
        log(f"플레이리스트 로드 실패: {e}", "error")
        return

    if playlist.is_variant:
        log("[*] 마스터 플레이리스트 감지. 스트림 선택 중...", "info")
        media_url = playlist.playlists[0].absolute_uri
        resp = await fetch_with_proxy(media_url, proxy_prefix)
        content = await resp.string()
        playlist = m3u8.loads(content, uri=media_url)

    segments = playlist.segments
    if not segments:
        log("세그먼트 정보를 찾을 수 없습니다.", "error")
        return

    total_available = len(segments)
    end_index = min(start_index + max_segments, total_available)
    target_segments = segments[start_index:end_index]
    count = len(target_segments)
    
    if start_index >= total_available:
        log(f"시작 인덱스({start_index})가 전체 세그먼트 수({total_available})보다 큽니다.", "error")
        return

    log('[*] 총 ' + str(total_available) + '개 중 ' + str(start_index) + '번부터 ' + str(count) + '개 분석 (' + str(start_index) + '~' + str(end_index-1) + ')', 'info')
    
    # 암호화 확인
    if any(seg.key for seg in segments):
        log("[!] 암호화된(AES-128 등) 세그먼트가 감지되었습니다. 현재 분석기는 암호화 해제를 지원하지 않아 결과가 부정확할 수 있습니다.", "warning")

    last_v_dts_end = None
    last_a_dts_end = None
    all_offsets = []
    all_raw_diffs = [] # 방향을 포함한 원시 변화량
    analysis_data = [] # 테이블용 데이터 수집
    last_gap_index = -1 # 마지막 GAP 발생 위치
    all_audio_gaps = []  # 세그먼트 간 오디오 연속성 갭
    all_dur_mismatches = []  # 오디오 실제 duration vs 선언 duration 차이
    all_audio_stddevs = []  # 세그먼트 내 오디오 PTS 간격 표준편차
    
    for i in range(count):
        actual_idx = start_index + i
        document.getElementById("status-text").innerText = '분석 중 (' + str(i+1) + '/' + str(count) + ')'
        seg = target_segments[i]
        log('Seg ' + str(actual_idx) + ': ' + seg.uri, 'header')
        
        try:
            r = await fetch_with_proxy(seg.absolute_uri, proxy_prefix)
            data = await r.bytes()
            ts_info = await window.parseSegmentTimestamps(Uint8Array.new(data).buffer)
            
            v = ts_info.video
            a = ts_info.audio
            
            v_start = v.firstPts if v.firstPts is not None else v.firstDts
            a_start = a.firstPts if a.firstPts is not None else a.firstDts

            # v2.1: Aresample 분석 데이터 추출
            seg_duration = seg.duration
            audio_actual_dur = float(a.actualDuration) if a.actualDuration else 0
            audio_pts_stddev = float(a.intervalStdDev) if a.intervalStdDev else 0
            
            # A/V Offset 및 Gap 확인
            offset = None
            has_gap = False
            raw_diff = 0
            if v_start is not None and a_start is not None:
                offset = v_start - a_start
                
                # 연속성 갭 확인 (0.5초 이상 갭 또는 시간 역전)
                if last_v_dts_end is not None:
                    v_diff = v_start - last_v_dts_end
                    if abs(v_diff) > 0.5 or v_diff < -0.1:
                        has_gap = True
                
                # 변화량(Raw Diff) 계산
                if all_offsets:
                    raw_diff = offset - all_offsets[-1]
                    if not has_gap:
                        all_raw_diffs.append(raw_diff)
                
                # 규칙성(Predictability) 체크 (v1.8 고도화)
                is_consistent = False
                if len(all_raw_diffs) >= 3:
                    recent = all_raw_diffs[-3:]
                    # 변화량 간의 차이가 1.5ms 이내면 매우 일관적 (Grid Alignment)
                    if (max(recent) - min(recent)) < 0.0015: 
                        is_consistent = True
                    # 혹은 절대값이 12ms 이하인 미세 보정이 유지될 때
                    elif max([abs(d) for d in recent]) < 0.012:
                        is_consistent = True
                
                # GAP 복구 분석
                recovery_info = ""
                if has_gap:
                    last_gap_index = actual_idx
                elif last_gap_index != -1:
                    gap_dist = actual_idx - last_gap_index
                    if is_consistent:
                        recovery_info = " (Stable after " + str(gap_dist) + " segs)"
                        last_gap_index = -1
                
                all_offsets.append(offset)
                
                offset_ms = offset * 1000
                sync_status = "✅ Synced"
                log_type = "success"
                
                # 진단 임계값 (v1.8): 규칙적이면 200ms까지 허용
                if abs(offset) >= 0.20 and not is_consistent:
                    sync_status = "🚨 CRITICAL"
                    log_type = "error"
                elif abs(offset) >= 0.12 or (abs(raw_diff) > 0.04 and not is_consistent):
                    sync_status = "⚠️ Warning"
                    log_type = "warning"
                
                diff_str = ' (Diff: {:.1f}ms'.format(raw_diff * 1000) + recovery_info + ')' if raw_diff != 0 else ""
                log('  🔗 Offset: ' + '{:.1f}'.format(offset_ms) + 'ms' + diff_str + ' [' + sync_status + ']', log_type)
                if has_gap:
                    log('  ℹ️ Discontinuity(Gap) 발생. 복구 패턴을 감시합니다.', 'info')

            # 그래프 렌더링
            canvas_id = 'chart-seg-' + str(actual_idx)
            log('<div class="chart-wrapper"><canvas id="' + canvas_id + '"></canvas></div>')
            window.renderSegmentChart(canvas_id, v.samples, a.samples)

            # v2.1: 세그먼트 간 오디오 연속성 분석
            audio_cont_gap = None
            if last_a_dts_end is not None and a_start is not None:
                audio_cont_gap = a_start - last_a_dts_end
                # GAP/역행 세그먼트 제외 — 소스 결함과 Aresample 미적용을 분리 판정
                if not has_gap and abs(audio_cont_gap) < 1.0:
                    all_audio_gaps.append(audio_cont_gap)

            audio_dur_mismatch = None
            if audio_actual_dur > 0 and seg_duration:
                audio_dur_mismatch = audio_actual_dur - seg_duration
                if not has_gap:
                    all_dur_mismatches.append(audio_dur_mismatch)

            if audio_pts_stddev > 0 and not has_gap:
                all_audio_stddevs.append(audio_pts_stddev)

            # 테이블용 데이터 저장
            analysis_data.append({
                "index": actual_idx,
                "v_start": v_start,
                "a_start": a_start,
                "offset": offset,
                "raw_diff": raw_diff,
                "consistent": is_consistent,
                "gap": has_gap,
                "audio_cont_gap": audio_cont_gap,
                "audio_dur_mismatch": audio_dur_mismatch,
                "audio_pts_stddev": audio_pts_stddev
            })
            
            last_v_dts_end = v.lastPts if v.lastPts is not None else v.lastDts
            last_a_dts_end = a.lastPts if a.lastPts is not None else a.lastDts
            
            window.updateProgress(int((i+1)/count * 100))
        except Exception as e:
            log(f"  [!] 세그먼트 오류: {e}", "error")

    # 요약 레포트
    if all_offsets:
        avg_offset = sum(all_offsets) / len(all_offsets)
        max_abs_offset = max([abs(o) for o in all_offsets])
        
        # v1.8: 통계 기반 동적 격자(Grid) 감지
        # 가장 흔하게 발생하는 지터(abs(raw_diff))를 격자로 추정
        jitters = [abs(round(d * 1000, 1)) for d in all_raw_diffs if abs(d) > 0.001]
        grid_ms = 0
        if jitters:
            from collections import Counter
            counts = Counter(jitters)
            grid_ms, _ = counts.most_common(1)[0]
        
        # v2.1: Aresample(async=1) 적용 여부 분석
        avg_audio_gap = 0
        max_audio_gap = 0
        avg_dur_mismatch = 0
        max_dur_mismatch = 0
        avg_audio_stddev = 0

        if all_audio_gaps:
            avg_audio_gap = sum([abs(g) for g in all_audio_gaps]) / len(all_audio_gaps)
            max_audio_gap = max([abs(g) for g in all_audio_gaps])
        if all_dur_mismatches:
            avg_dur_mismatch = sum([abs(m) for m in all_dur_mismatches]) / len(all_dur_mismatches)
            max_dur_mismatch = max([abs(m) for m in all_dur_mismatches])
        if all_audio_stddevs:
            avg_audio_stddev = sum(all_audio_stddevs) / len(all_audio_stddevs)

        # Aresample 판정: GAP/역행 제외 후 정상 세그먼트 기준
        # Audio Gap > 150ms (AAC 프레임 배수 ~23ms×6 허용), Duration 편차 > 100ms, StdDev > 5ms
        aresample_missing = (avg_audio_gap > 0.15) or (avg_dur_mismatch > 0.1) or (avg_audio_stddev > 0.005)

        # v2.0: 타임라인 무결성(Timeline Monotonicity) 체크
        backward_jump_detected = False
        large_gap_detected = False
        jump_info = ""
        
        for j in range(1, len(analysis_data)):
            curr = analysis_data[j]
            prev = analysis_data[j-1]
            
            # 1. Backward Jump 감지 (Monotonicity Check)
            v_diff = curr['v_start'] - prev['v_start']
            a_diff = curr['a_start'] - prev['a_start']
            
            # v2.0: 시간 역행 임계값 (0.1s 이상 과거로 갈 때 치명적으로 간주)
            if v_diff < -0.1 or a_diff < -0.1:
                backward_jump_detected = True
                jump_info = f"#{prev['index']} -> #{curr['index']} 지점에서 시간 역행 감지 ({prev['v_start']:.3f}s -> {curr['v_start']:.3f}s)"
                break
                
            # 2. Qualitative GAP Analysis (10초 이상의 거대 GAP)
            if curr['gap']:
                # 이전 데이터와의 간격이 10초를 넘으면 심각한 결함으로 간주
                if v_diff > 10.0 or a_diff > 10.0:
                    large_gap_detected = True
        
        # v1.9: 영점 교차율(Zero-crossing Rate) 및 진동 분석 (GAP 면역 체계)
        zcr_count = 0
        fatal_osc_count = 0
        amplitudes_at_cross = []
        recovery_segments_window = 3 # GAP 이후 면역(제외)할 세그먼트 수
        gap_indices = [idx for idx, row in enumerate(analysis_data) if row['gap']]
        
        if len(all_offsets) >= 2:
            for j in range(1, len(all_offsets)):
                # GAP 면역 체크: 현재 세그먼트 혹은 직전 3개 이내에 GAP이 있었다면 ZCR 분석 제외
                is_in_recovery = False
                for g_idx in gap_indices:
                    if 0 <= (j - g_idx) <= recovery_segments_window:
                        is_in_recovery = True
                        break
                
                if is_in_recovery:
                    continue
                    
                # 부호 전환 감지 (+ -> - 또는 - -> +)
                if all_offsets[j] * all_offsets[j-1] < 0:
                    zcr_count += 1
                    # 교차 지점에서의 진폭
                    amp = abs(all_offsets[j] - all_offsets[j-1])
                    amplitudes_at_cross.append(amp)
                    # 교차 시 진폭이 30ms 이상이고 불규칙적이면 Fatal로 간주 (면역 기간 제외)
                    if amp > 0.03:
                        fatal_osc_count += 1
        
        # 진단 엔진 v2.0 판정 로직 (우선순위: 타임라인 > 진동 > 오차)
        is_oscillating = fatal_osc_count >= 2
        is_grid_stable = not is_oscillating and len(all_raw_diffs) >= 3
        has_any_gap = len(gap_indices) > 0
        
        status_label = "정상"
        status_color = "var(--success)"
        
        if backward_jump_detected:
            status_label = "재생 불가 (역행)"
            status_color = "var(--error)"
        elif is_oscillating:
            status_label = "위험 (진동)"
            status_color = "var(--error)"
        elif large_gap_detected:
            status_label = "치명적 결함 (거대 GAP)"
            status_color = "var(--error)"
        elif aresample_missing:
            status_label = "위험 (Aresample 미적용)"
            status_color = "var(--error)"
        elif has_any_gap and is_grid_stable:
            status_label = "정상 (복구됨)"
            status_color = "var(--success)"
        elif max_abs_offset > 0.3:
            status_label = "위험 (거대 오차)"
            status_color = "var(--error)"
        elif max_abs_offset > 0.15 and not is_grid_stable:
            status_label = "주의"
            status_color = "var(--warning)"
            
        avg_offset_ms = '{:.1f}'.format(avg_offset*1000) + 'ms'
        
        dashboard_html = '<div class="result-dashboard">'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">진단 결과</div>'
        dashboard_html += '        <div class="stat-value" style="color: ' + status_color + '">' + status_label + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">평균 Offset</div>'
        dashboard_html += '        <div class="stat-value">' + avg_offset_ms + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">추정 격자(Grid)</div>'
        dashboard_html += '        <div class="stat-value">' + ('{:.1f}ms'.format(grid_ms) if grid_ms > 0 else "N/A") + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">Audio 연속성 Gap</div>'
        dashboard_html += '        <div class="stat-value">' + ('{:.1f}ms'.format(avg_audio_gap * 1000) if all_audio_gaps else "N/A") + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">Duration 편차</div>'
        dashboard_html += '        <div class="stat-value">' + ('{:.1f}ms'.format(avg_dur_mismatch * 1000) if all_dur_mismatches else "N/A") + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">Aresample 판정</div>'
        aresample_color = "var(--error)" if aresample_missing else "var(--success)"
        aresample_text = "미적용 의심" if aresample_missing else "적용됨"
        dashboard_html += '        <div class="stat-value" style="color: ' + aresample_color + '">' + aresample_text + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '</div>'
        
        document.getElementById("summary-dashboard").innerHTML = dashboard_html
        
        log('[*] 분석 상세 결과 (v2.1.1)', 'header')
        table_html = '<table class="summary-table"><thead><tr>'
        table_html += '<th>#</th><th>V-Start</th><th>A-Start</th><th>Offset</th><th>Jitter</th><th>A-Gap</th><th>상세</th>'
        table_html += '</tr></thead><tbody>'
        
        for idx, row in enumerate(analysis_data):
            off_val = row['offset']
            off_str = '{:.1f}ms'.format(off_val * 1000) if off_val is not None else "-"
            jit_val = abs(row['raw_diff'])
            jit_str = '{:.1f}ms'.format(jit_val * 1000) if jit_val > 0 else "-"
            badge = ""
            
            # v2.0: 타임라인 무결성 위반 시 시각적 표시
            is_backward = False
            if idx > 0:
                if row['v_start'] < analysis_data[idx-1]['v_start'] - 0.1:
                    is_backward = True

            if off_val is not None:
                if is_backward: badge = '<span class="badge badge-error">TIME-REVERSE</span>'
                elif row['consistent']: badge = '<span class="badge badge-success">Consistent</span>'
                elif abs(off_val) < 0.05: badge = '<span class="badge badge-success">Synced</span>'
                elif abs(off_val) < 0.15: badge = '<span class="badge badge-warning">Skew</span>'
                else: badge = '<span class="badge badge-error">Critical</span>'
            
            if row['gap']:
                # 10초 넘는 GAP일 때 전용 배지
                if idx > 0 and (row['v_start'] - analysis_data[idx-1]['v_start'] > 10.0):
                    badge += ' <span class="badge" style="background: #be185d">HUGE-GAP</span>'
                else:
                    badge += ' <span class="badge" style="background: #64748b">GAP</span>'
            elif row['raw_diff'] != 0:
                # v1.9: GAP 면역 기간(3개 세그먼트)에는 ZCR-ZIG 미표시
                idx_in_data = row['index'] - start_index
                if idx_in_data > 0:
                    curr_off = row['offset']
                    prev_off = analysis_data[idx_in_data-1]['offset']
                    if curr_off is not None and prev_off is not None:
                        if curr_off * prev_off < 0 and abs(curr_off - prev_off) > 0.03:
                            # 최근 3개 이내에 GAP이 없었을 때만 배지 표시
                            was_near_gap = False
                            for g_idx in gap_indices:
                                if 0 <= (idx - g_idx) <= recovery_segments_window:
                                    was_near_gap = True
                                    break
                            if not was_near_gap:
                                badge += ' <span class="badge" style="background: #f43f5e">ZCR-ZIG</span>'
            
            # 행 스타일 추가 (타임라인 위반 시 강조)
            row_style = ' style="background: rgba(244, 63, 94, 0.1)"' if is_backward else ""
            # v2.1: Audio Gap / Duration Drift 배지
            a_gap_val = row.get('audio_cont_gap')
            a_gap_str = '{:.1f}ms'.format(a_gap_val * 1000) if a_gap_val is not None else "-"
            if a_gap_val is not None and abs(a_gap_val) > 0.15:
                badge += ' <span class="badge" style="background: #7c3aed">AUDIO-GAP</span>'
            if row.get('audio_dur_mismatch') is not None and abs(row['audio_dur_mismatch']) > 0.1:
                badge += ' <span class="badge" style="background: #ea580c">DUR-DRIFT</span>'

            table_html += '<tr' + row_style + '><td>' + str(row['index']) + '</td><td>' + '{:.3f}'.format(row['v_start']) + '</td><td>' + '{:.3f}'.format(row['a_start']) + '</td><td>' + off_str + '</td><td>' + jit_str + '</td><td>' + a_gap_str + '</td><td>' + badge + '</td></tr>'
        table_html += "</tbody></table>"
        log(table_html)

        # 스마트 진단 가이드 (v2.0)
        log("[*] 스마트 진단 보고서 (v2.1.1)", "header")
        if backward_jump_detected:
            log("🚫 <b>FATAL: TIMELINE REVERSAL (재생 불가):</b> 시간이 과거로 역행하는 치명적인 오류가 포착되었습니다. " + jump_info + " 안드로이드 하드웨어 디코더는 이 지점에서 재생을 중단합니다. 소스 머징(Merging) 과정의 결함이 의심됩니다.", "error")
        elif large_gap_detected:
            log("🚫 <b>FATAL: HUGE GAP (인코딩 결함):</b> 10초 이상의 거대한 시간 공백이 발견되었습니다. 단순 네트워크 지연이 아닌 소스 레벨의 데이터 누락으로 간주됩니다.", "error")
        elif has_any_gap and is_grid_stable:
            log("✅ <b>STABLE AFTER GAP (정상):</b> 불연속(GAP)이 발생했으나 이후 스트림이 매우 안정적으로 회복되었습니다. 안드로이드 크롬에서 정상 재생 가능합니다.", "success")
        elif is_grid_stable:
            log("✅ <b>STABLE GRID (정상):</b> 동적 격자({:.1f}ms) 기반의 보정 패턴이 매우 안정적입니다. 정상 재생 가능합니다.".format(grid_ms), "success")
        elif is_oscillating:
            log("🚫 <b>FATAL OSCILLATION (위험):</b> 연속 비트스트림 내에서 제어가 불가능한 진동이 감지되었습니다. 버퍼 결함을 유발하는 핵심 요인입니다.", "error")
        else:
            log("ℹ️ <b>분석 완료:</b> 스트림 패턴이 대체로 양호합니다. (타임라인 무결성 확보됨)", "info")

        # v2.1: Aresample 전용 진단 보고서
        log("[*] Aresample(async=1) 분석 보고서 (v2.1.1)", "header")
        if aresample_missing:
            evidence = []
            if avg_audio_gap > 0.15:
                evidence.append("평균 오디오 연속성 Gap: {:.1f}ms (기준: &lt;150ms)".format(avg_audio_gap * 1000))
            if avg_dur_mismatch > 0.1:
                evidence.append("평균 Duration 편차: {:.1f}ms (기준: &lt;100ms)".format(avg_dur_mismatch * 1000))
            if avg_audio_stddev > 0.005:
                evidence.append("평균 오디오 PTS 간격 편차: {:.3f}ms (기준: &lt;5ms)".format(avg_audio_stddev * 1000))
            log("🚫 <b>aresample=async=1 미적용 의심:</b> 오디오 타임스탬프 연속성이 확보되지 않았습니다. FFmpeg 인코딩 시 <code>-af aresample=async=1</code> 옵션 적용을 권장합니다.", "error")
            for ev in evidence:
                log("  → " + ev, "warning")
            log("ℹ️ <b>영향:</b> 안드로이드 크롬의 MSE/MediaCodec은 오디오 타임스탬프의 연속성을 엄격히 요구합니다. 이 옵션 없이는 오디오 디코더가 갭/겹침을 처리하지 못해 재생이 중단될 수 있습니다.", "info")
        else:
            log("✅ <b>aresample=async=1 적용 확인:</b> 오디오 타임스탬프가 연속적이며 세그먼트 간 정상적인 연결이 확인되었습니다.", "success")
            if all_audio_gaps:
                log("  → 평균 오디오 연속성 Gap: {:.1f}ms / 최대: {:.1f}ms".format(avg_audio_gap * 1000, max_audio_gap * 1000), "info")
            if all_dur_mismatches:
                log("  → 평균 Duration 편차: {:.1f}ms / 최대: {:.1f}ms".format(avg_dur_mismatch * 1000, max_dur_mismatch * 1000), "info")

    log("[*] 모든 분석 완료", "header")
