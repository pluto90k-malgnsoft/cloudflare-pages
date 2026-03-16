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
    all_jitters = [] # 세그먼트 간 오프셋 변화량 (Gap 제외)
    analysis_data = [] # 테이블용 데이터 수집
    
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
            
            if v_start is not None:
                log('  Video PTS: ' + '{:.3f}'.format(v.firstPts) + ' | DTS: ' + '{:.3f}'.format(v.firstDts), 'info')
            if a_start is not None:
                log('  Audio PTS: ' + '{:.3f}'.format(a.firstPts) + ' | DTS: ' + '{:.3f}'.format(a.firstDts), 'info')
            
            # A/V Offset 및 Gap 확인
            offset = None
            has_gap = False
            jitter = 0
            if v_start is not None and a_start is not None:
                offset = v_start - a_start
                
                # 연속성 갭 확인 (0.5초 이상 갭 또는 시간 역전)
                if last_v_dts_end is not None:
                    v_diff = v_start - last_v_dts_end
                    if abs(v_diff) > 0.5 or v_diff < -0.1:
                        has_gap = True
                
                # 지터(Jitter) 계산: 이전 세그먼트 오프셋과의 차이
                if all_offsets:
                    jitter = abs(offset - all_offsets[-1])
                    if not has_gap: # Gap 구간의 지터는 시스템 불안정으로 보지 않음
                        all_jitters.append(jitter)
                
                all_offsets.append(offset)
                
                offset_ms = offset * 1000
                sync_status = "✅ Synced"
                log_type = "success"
                
                # 임계값 완화: 150ms 이상만 위험, 100ms 이상 주의 (v1.5)
                if abs(offset) >= 0.15:
                    sync_status = "🚨 CRITICAL"
                    log_type = "error"
                elif abs(offset) >= 0.1:
                    sync_status = "⚠️ Warning"
                    log_type = "warning"
                
                jitter_str = ' (Jitter: {:.1f}ms)'.format(jitter * 1000) if jitter > 0 else ""
                log('  🔗 Offset: ' + '{:.1f}'.format(offset_ms) + 'ms' + jitter_str + ' [' + sync_status + ']', log_type)
                if has_gap:
                    log('  ℹ️ Discontinuity(Gap) 감지됨. 이 구간의 지터는 정상 범위로 간주합니다.', 'info')

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
                "jitter": jitter,
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
        offset_range = max(all_offsets) - min(all_offsets) 
        max_clean_jitter = max(all_jitters) if all_jitters else 0
        
        # 지터의 규칙성(Linearity) 분석: 지터들 사이의 변화가 2ms 이내면 매우 일정함
        jitter_diffs = [abs(all_jitters[j] - all_jitters[j-1]) for j in range(1, len(all_jitters))]
        is_linear = len(jitter_diffs) > 0 and max(jitter_diffs) < 0.005 

        # 진단 임계값 (v1.5 최적화)
        is_stable = is_linear or (offset_range < 0.03 and max_clean_jitter < 0.015)
        is_jagged = max_clean_jitter > 0.05 # 50ms 이상 불규칙하게 튈 때만 위험 
        is_aligned = max_abs_offset < 0.01
        
        status_label = "정상"
        status_color = "var(--success)"
        if max_abs_offset > 0.25 or is_jagged: # 250ms 이상만 위험
            status_label = "위험"
            status_color = "var(--error)"
        elif max_abs_offset > 0.1 or offset_range > 0.08:
            status_label = "주의"
            status_color = "var(--warning)"
            
        avg_offset_ms = '{:.1f}'.format(avg_offset*1000) + 'ms'
        max_jitter_ms = '{:.1f}'.format(max_clean_jitter*1000) + 'ms'
        
        dashboard_html = '<div class="result-dashboard">'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">상태</div>'
        dashboard_html += '        <div class="stat-value" style="color: ' + status_color + '">' + status_label + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">평균 Offset</div>'
        dashboard_html += '        <div class="stat-value">' + avg_offset_ms + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">유효 지터(Jitter)</div>'
        dashboard_html += '        <div class="stat-value">' + max_jitter_ms + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '</div>'
        
        document.getElementById("summary-dashboard").innerHTML = dashboard_html
        
        log('[*] 분석 상세 결과 (v1.5)', 'header')
        table_html = '<table class="summary-table"><thead><tr>'
        table_html += '<th>#</th><th>V-Start</th><th>A-Start</th><th>Offset</th><th>Jitter</th><th>상세</th>'
        table_html += '</tr></thead><tbody>'
        
        for row in analysis_data:
            v_s = '{:.3f}'.format(row['v_start']) if row['v_start'] is not None else "-"
            a_s = '{:.3f}'.format(row['a_start']) if row['a_start'] is not None else "-"
            off_val = row['offset']
            off_str = "-"
            jit_str = '{:.1f}ms'.format(row['jitter'] * 1000) if row['jitter'] > 0 else "-"
            badge = ""
            
            if off_val is not None:
                off_str = '{:.1f}ms'.format(off_val * 1000)
                # 테이블 내 배지 임계값도 상향 (v1.5)
                if abs(off_val) < 0.03: badge = '<span class="badge badge-success">Synced</span>'
                elif abs(off_val) < 0.1: badge = '<span class="badge badge-warning">Skew</span>'
                else: badge = '<span class="badge badge-error">Large</span>'
            
            if row['gap']:
                badge += ' <span class="badge" style="background: #64748b">GAP</span>' # 차분한 색상
            elif row['jitter'] > 0.05:
                badge += ' <span class="badge" style="background: #f43f5e">JAG</span>'
            
            table_html += '<tr><td>' + str(row['index']) + '</td><td>' + v_s + '</td><td>' + a_s + '</td><td>' + off_str + '</td><td>' + jit_str + '</td><td>' + badge + '</td></tr>'
        table_html += "</tbody></table>"
        log(table_html)

        # 스마트 진단 가이드 (v1.5)
        log("[*] 스마트 진단 보고서 (v1.5)", "header")
        if is_aligned:
            log("✅ <b>안정적:</b> 모든 데이터가 동기화 범내에 있습니다.", "success")
        elif is_stable:
            log("ℹ️ <b>정상 (규칙적 흐름):</b> 오프셋이 존재하나 흐름이 선형적이거나 매우 일정합니다. 안드로이드 크롬 등 현대적인 브라우저에서 문제없이 재생 가능한 상태입니다.", "success")
        elif is_jagged:
            log("🚫 <b>불안정 (비선형 지터):</b> 세그먼트 간 오프셋이 불규칙하게 튑니다. 인코딩 설정(aresample)을 재점검하시기 바랍니다.", "error")
        else:
            log("⚠️ <b>주의:</b> 오프셋이 다소 높으나, 흐름이 일정하다면 대부분의 환경에서 정상 재생됩니다.", "warning")
            
    log("[*] 모든 분석 완료", "header")

    log("[*] 모든 분석 완료", "header")
