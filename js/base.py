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
            
            # A/V Offset 및 Drift 계산
            if v_start is not None and a_start is not None:
                offset = v_start - a_start
                offset_ms = offset * 1000
                drift = 0
                
                # 연속성 갭 확인 (0.5초 이상 갭/오버랩이 있으면 Drift 계산 제외)
                has_gap = False
                if last_v_dts_end is not None and abs(v_start - last_v_dts_end) > 0.5:
                    has_gap = True
                
                if all_offsets and not has_gap:
                    drift = abs(offset - all_offsets[-1])
                
                all_offsets.append(offset)
                
                sync_status = "✅ Synced"
                log_type = "success"
                
                if abs(offset) >= 0.1:
                    sync_status = "🚨 CRITICAL (Android Failure Risk)"
                    log_type = "error"
                elif abs(offset) >= 0.06:
                    sync_status = "⚠️ Warning (Mobile Skew)"
                    log_type = "warning"
                
                log('  🔗 A/V Offset: ' + '{:.4f}'.format(offset) + 's (' + '{:.1f}'.format(offset_ms) + 'ms) [' + sync_status + ']', log_type)
                
                if not has_gap and drift > 0.05:
                    log('    📉 High Drift detected: ' + '{:.1f}'.format(drift*1000) + 'ms change from prev segment', 'error')
                elif has_gap:
                    log('    ℹ️ Continuity Gap detected. Skipping drift analysis for this segment.', 'info')
                
                if abs(offset) < 0.001:
                    log("    💡 FFMPEG -async 1 적용 가능성 높음 (Start aligned)", "info")
            
            # 연속성 체크 (Video 기준)
            if v_start is not None and last_v_dts_end is not None:
                v_diff = v_start - last_v_dts_end
                if abs(v_diff) > 0.1:
                    log('  🎬 Video Gap/Overlap: ' + '{:.3f}'.format(v_diff) + 's', 'error')
                else:
                    log('  🎬 Video Continuity: OK (' + '{:.3f}'.format(v_diff) + 's)', 'success')

            # 연속성 체크 (Audio 기준)
            if a_start is not None and last_a_dts_end is not None:
                a_diff = a_start - last_a_dts_end
                if abs(a_diff) > 0.1:
                    log('  🎵 Audio Gap/Overlap: ' + '{:.3f}'.format(a_diff) + 's', 'error')
                
            # 그래프용 캔버스 생성 및 렌더링
            canvas_id = 'chart-seg-' + str(actual_idx)
            log('<div class="chart-wrapper"><canvas id="' + canvas_id + '"></canvas></div>')
            window.renderSegmentChart(canvas_id, v.samples, a.samples)

            # 테이블용 데이터 저장
            analysis_data.append({
                "index": actual_idx,
                "v_start": v_start,
                "a_start": a_start,
                "offset": v_start - a_start if v_start is not None and a_start is not None else None
            })
            
            last_v_dts_end = v.lastPts if v.lastPts is not None else v.lastDts
            last_a_dts_end = a.lastPts if a.lastPts is not None else a.lastDts
            
            window.updateProgress(int((i+1)/count * 100))
        except Exception as e:
            log(f"  [!] 세그먼트 오류: {e}", "error")

    # 요약 레포트 및 테이블 출력
    if all_offsets:
        avg_offset = sum(all_offsets) / len(all_offsets)
        max_offset = max([abs(o) for o in all_offsets])
        variance = max(all_offsets) - min(all_offsets)
        
        # FFMPEG 옵션(-async 1 / aresample=async=1) 적용 판단
        # 특징: 모든 세그먼트에서 V/A 시작 지점이 1ms 이하로 일치하거나, Jitter가 거의 없음
        is_ffmpeg_async = max_offset < 0.002 and variance < 0.001
        
        # 대시보드 출력용 변수 사전 준비
        status_label = "정상"
        status_color = "var(--success)"
        if max_offset > 0.1:
            status_label = "위험 (재생불가 가능성)"
            status_color = "var(--error)"
        elif max_offset > 0.06 or variance > 0.05:
            status_label = "주의 (싱크 불안정)"
            status_color = "var(--warning)"
            
        avg_offset_ms = '{:.1f}'.format(avg_offset*1000) + 'ms'
        ffmpeg_badge = "✅ 적용됨" if is_ffmpeg_async else "❌ 미감지"

        # f-string 대신 문자열 더하기(+) 사용 (IDE 린트 오류 및 파싱 이슈 완전 방지)
        dashboard_html = '<div class="result-dashboard">'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">최종 상태</div>'
        dashboard_html += '        <div class="stat-value" style="color: ' + status_color + '">' + status_label + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">평균 Offset</div>'
        dashboard_html += '        <div class="stat-value">' + avg_offset_ms + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '    <div class="stat-card">'
        dashboard_html += '        <div class="stat-label">FFMPEG 옵션 감지</div>'
        dashboard_html += '        <div class="stat-value">' + ffmpeg_badge + '</div>'
        dashboard_html += '    </div>'
        dashboard_html += '</div>'
        
        document.getElementById("summary-dashboard").innerHTML = dashboard_html
        
        log('[*] 분석 완료 요약', 'header')
        
        # 상세 데이터 테이블 생성 (트리플 쿼트 대신 안전한 문자열 연결 사용)
        table_html = '<table class="summary-table">'
        table_html += '    <thead>'
        table_html += '        <tr>'
        table_html += '            <th>#</th>'
        table_html += '            <th>Video Start (s)</th>'
        table_html += '            <th>Audio Start (s)</th>'
        table_html += '            <th>A/V Offset (ms)</th>'
        table_html += '            <th>상태</th>'
        table_html += '        </tr>'
        table_html += '    </thead>'
        table_html += '    <tbody>'
        for row in analysis_data:
            idx = row['index']
            v_s = '{:.3f}'.format(row['v_start']) if row['v_start'] is not None else "-"
            a_s = '{:.3f}'.format(row['a_start']) if row['a_start'] is not None else "-"
            off_val = row['offset']
            off_str = "-"
            badge = ""
            
            if off_val is not None:
                off_ms = off_val * 1000
                off_str = '{:.1f}'.format(off_ms) + 'ms'
                if abs(off_val) < 0.01: badge = '<span class="badge badge-success">Synced</span>'
                elif abs(off_val) < 0.06: badge = '<span class="badge badge-warning">Small Skew</span>'
                else: badge = '<span class="badge badge-error">Critical</span>'
            
            table_html += '                <tr>'
            table_html += '                    <td>' + str(idx) + '</td>'
            table_html += '                    <td>' + v_s + '</td>'
            table_html += '                    <td>' + a_s + '</td>'
            table_html += '                    <td>' + off_str + '</td>'
            table_html += '                    <td>' + badge + '</td>'
            table_html += '                </tr>'
        table_html += "</tbody></table>"
        log(table_html)

        # 팁 추가
        if is_ffmpeg_async:
            log("💡 <b>진단 결과:</b> FFMPEG의 오디오 동기화 옵션이 정상적으로 작동하고 있는 것으로 보입니다. 비디오와 오디오의 시작점이 매칭되어 있습니다.", "success")
        elif max_offset > 0.06:
            log("💡 <b>권장 작업:</b> 현재 싱크 차이가 큽니다. FFMPEG 사용 시 <code>-async 1</code> 또는 <code>aresample=async=1</code> 옵션을 추가하여 오디오 시작점을 비디오에 맞추는 것을 권장합니다.", "warning")

    log("[*] 모든 분석 완료", "header")
