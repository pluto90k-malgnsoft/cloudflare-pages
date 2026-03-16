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
            if v_start is not None and a_start is not None:
                offset = v_start - a_start
                all_offsets.append(offset)
                
                # 연속성 갭 확인 (0.5초 이상 갭 또는 시간이 뒤로 감)
                if last_v_dts_end is not None:
                    v_diff = v_start - last_v_dts_end
                    if abs(v_diff) > 0.5 or v_diff < -0.1:
                        has_gap = True
                
                offset_ms = offset * 1000
                sync_status = "✅ Synced"
                log_type = "success"
                
                if abs(offset) >= 0.1:
                    sync_status = "🚨 CRITICAL"
                    log_type = "error"
                elif abs(offset) >= 0.06:
                    sync_status = "⚠️ Warning"
                    log_type = "warning"
                
                log('  🔗 Offset: ' + '{:.1f}'.format(offset_ms) + 'ms [' + sync_status + ']', log_type)
                if has_gap:
                    log('  ⚠️ 불연속성(Gap/Discontinuity) 감지됨!', 'warning')

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
        offset_range = max(all_offsets) - min(all_offsets) # 편차
        
        # FFMPEG 옵션 감지 로직 고도화
        # 1. 절대값이 매우 낮음 (완전 동기화)
        # 2. 혹은 절대값은 있어도 편차가 매우 낮음 (고정 지연 - async 옵션은 작동 중이나 소스 지연 존재)
        is_stable = offset_range < 0.01 
        is_aligned = max_abs_offset < 0.005
        
        status_label = "정상"
        status_color = "var(--success)"
        if max_abs_offset > 0.1:
            status_label = "위험"
            status_color = "var(--error)"
        elif max_abs_offset > 0.06 or offset_range > 0.05:
            status_label = "주의"
            status_color = "var(--warning)"
            
        avg_offset_ms = '{:.1f}'.format(avg_offset*1000) + 'ms'
        variance_ms = '{:.1f}'.format(offset_range*1000) + 'ms'
        
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
        dashboard_html += '        <div class="stat-label">오프셋 편차(Jitter)</div>'
        dashboard_html += '        <div class="stat-value">' + variance_ms + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '</div>'
        
        document.getElementById("summary-dashboard").innerHTML = dashboard_html
        
        log('[*] 분석 상세 결과', 'header')
        table_html = '<table class="summary-table"><thead><tr>'
        table_html += '<th>#</th><th>V-Start</th><th>A-Start</th><th>Offset</th><th>상태/Gap</th>'
        table_html += '</tr></thead><tbody>'
        
        for row in analysis_data:
            v_s = '{:.3f}'.format(row['v_start']) if row['v_start'] is not None else "-"
            a_s = '{:.3f}'.format(row['a_start']) if row['a_start'] is not None else "-"
            off_val = row['offset']
            off_str = "-"
            badge = ""
            
            if off_val is not None:
                off_str = '{:.1f}ms'.format(off_val * 1000)
                if abs(off_val) < 0.02: badge = '<span class="badge badge-success">Synced</span>'
                elif abs(off_val) < 0.06: badge = '<span class="badge badge-warning">Skew</span>'
                else: badge = '<span class="badge badge-error">Critical</span>'
            
            if row['gap']:
                badge += ' <span class="badge" style="background: #f43f5e">GAP</span>'
            
            table_html += '<tr><td>' + str(row['index']) + '</td><td>' + v_s + '</td><td>' + a_s + '</td><td>' + off_str + '</td><td>' + badge + '</td></tr>'
        table_html += "</tbody></table>"
        log(table_html)

        # 스마트 진단 가이드
        log("[*] 스마트 진단 보고서 (v1.3)", "header")
        if is_aligned:
            log("✅ <b>분석 결과:</b> 비디오와 오디오가 완벽하게 동기화되어 있습니다. FFmpeg 옵션이 최적으로 작동 중입니다.", "success")
        elif is_stable:
            log("ℹ️ <b>분석 결과 (고정 오프셋):</b> 오프셋이 약 " + avg_offset_ms + "로 일정하게 유지되고 있습니다. 이는 FFmpeg 옵션은 작동 중이나, 소스 단계의 초기 지연(Encoder Latency)이 포함된 상태입니다. 실감상에는 문제가 없을 가능성이 높습니다.", "info")
        else:
            log("⚠️ <b>분석 결과 (가변 드리프트):</b> 오프셋이 일정하지 않고 변동(편차 " + variance_ms + ")이 큽니다. FFmpeg에서 <code>-async 1</code> 또는 <code>aresample=async=1</code> 옵션이 누락되었거나, 소스 자체의 타임스탬프가 불안정할 수 있습니다.", "warning")
            
        if any(row['gap'] for row in analysis_data):
            log("🚨 <b>주의:</b> 스트림 중간에 타임스탬프 불연속성(Gap)이 발견되었습니다. 이는 소스 파일의 끊김이나 잘못된 세그먼팅으로 인해 발생하며, FFmpeg 옵션만으로는 해결되지 않을 수 있습니다.", "error")

    log("[*] 모든 분석 완료", "header")

    log("[*] 모든 분석 완료", "header")
