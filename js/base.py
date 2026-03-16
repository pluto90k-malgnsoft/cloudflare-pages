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
                
                # 규칙성(Predictability) 체크 (v1.7)
                is_consistent = False
                if len(all_raw_diffs) >= 3:
                    recent = all_raw_diffs[-3:]
                    # 변화량 간의 차이가 1.5ms 이내면 매우 일관적 (Grid Alignment)
                    if (max(recent) - min(recent)) < 0.0015: 
                        is_consistent = True
                    # 혹은 절대값이 10ms 이하인 미세 보정이 유지될 때
                    elif max([abs(d) for d in recent]) < 0.01:
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
                
                # 진단 임계값 (v1.7): 규칙적이면 200ms까지 허용 (실환경 Resilience 반영)
                if abs(offset) >= 0.20 and not is_consistent:
                    sync_status = "🚨 CRITICAL"
                    log_type = "error"
                elif abs(offset) >= 0.12 or (abs(raw_diff) > 0.035 and not is_consistent):
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

            # 테이블용 데이터 저장
            analysis_data.append({
                "index": actual_idx,
                "v_start": v_start,
                "a_start": a_start,
                "offset": offset,
                "raw_diff": raw_diff,
                "consistent": is_consistent,
                "gap": has_gap
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
        
        # 지그재그 진동(Oscillation) 최종 판정 (v1.7 상향 조정)
        oscillation_count = 0
        major_jitter_count = 0
        if len(all_raw_diffs) >= 2:
            for j in range(1, len(all_raw_diffs)):
                # 부호가 바뀌고 진폭이 30ms 이상일 때만 위험한 진동으로 간주
                if all_raw_diffs[j] * all_raw_diffs[j-1] < 0 and abs(all_raw_diffs[j]) > 0.03:
                    oscillation_count += 1
                if abs(all_raw_diffs[j]) > 0.05:
                    major_jitter_count += 1
        
        is_oscillating = oscillation_count >= 2
        is_stable_drift = not is_oscillating and major_jitter_count == 0
        
        status_label = "정상"
        status_color = "var(--success)"
        if is_oscillating:
            status_label = "위험 (진동)"
            status_color = "var(--error)"
        elif max_abs_offset > 0.3:
            status_label = "위험 (거대 오차)"
            status_color = "var(--error)"
        elif max_abs_offset > 0.15 and not is_stable_drift:
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
        dashboard_html += '        <div class="stat-label">예측 가능성</div>'
        dashboard_html += '        <div class="stat-value">' + ("높음" if is_stable_drift else "낮음") + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '</div>'
        
        document.getElementById("summary-dashboard").innerHTML = dashboard_html
        
        log('[*] 분석 상세 결과 (v1.7)', 'header')
        table_html = '<table class="summary-table"><thead><tr>'
        table_html += '<th>#</th><th>V-Start</th><th>A-Start</th><th>Offset</th><th>Jitter</th><th>상세</th>'
        table_html += '</tr></thead><tbody>'
        
        for row in analysis_data:
            off_val = row['offset']
            off_str = '{:.1f}ms'.format(off_val * 1000) if off_val is not None else "-"
            jit_val = abs(row['raw_diff'])
            jit_str = '{:.1f}ms'.format(jit_val * 1000) if jit_val > 0 else "-"
            badge = ""
            
            if off_val is not None:
                if row['consistent']: badge = '<span class="badge badge-success">Consistent</span>'
                elif abs(off_val) < 0.05: badge = '<span class="badge badge-success">Synced</span>'
                elif abs(off_val) < 0.15: badge = '<span class="badge badge-warning">Skew</span>'
                else: badge = '<span class="badge badge-error">Critical</span>'
            
            if row['gap']:
                badge += ' <span class="badge" style="background: #64748b">GAP</span>'
            elif row['raw_diff'] != 0:
                # v1.7: 30ms 이상의 급격한 방향 전환만 ZIGZAG 표시
                idx_in_data = row['index'] - start_index
                if idx_in_data > 0:
                    prev_diff = analysis_data[idx_in_data-1]['raw_diff']
                    if row['raw_diff'] * prev_diff < 0 and abs(row['raw_diff']) > 0.03:
                        badge += ' <span class="badge" style="background: #f43f5e">ZIGZAG</span>'
            
            table_html += '<tr><td>' + str(row['index']) + '</td><td>' + '{:.3f}'.format(row['v_start']) + '</td><td>' + '{:.3f}'.format(row['a_start']) + '</td><td>' + off_str + '</td><td>' + jit_str + '</td><td>' + badge + '</td></tr>'
        table_html += "</tbody></table>"
        log(table_html)

        # 스마트 진단 가이드 (v1.7)
        log("[*] 스마트 진단 보고서 (v1.7)", "header")
        if is_stable_drift:
            log("✅ <b>STABLE (정상):</b> 오차가 존재하나 매우 규칙적이거나 미세한 보정(7.8ms 격자 등) 수준입니다. 안드로이드 크롬에서 문제없이 재생 가능합니다.", "success")
        elif is_oscillating:
            log("🚫 <b>FATAL OSCILLATION (위험):</b> 오차가 30ms 이상 큰 폭으로 요동치고 있습니다. 이는 디코더 버퍼를 교란하여 재생 중단을 유발합니다.", "error")
        elif max_abs_offset > 0.25:
            log("⚠️ <b>LARGE DELAY (주의):</b> 오차가 전반적으로 큽니다. 네트워크 환경이 불안정할 경우 끊김이 발생할 수 있습니다.", "warning")
        else:
            log("ℹ️ <b>분석 완료:</b> 스트림 패턴이 양호합니다.", "info")

    log("[*] 모든 분석 완료", "header")
