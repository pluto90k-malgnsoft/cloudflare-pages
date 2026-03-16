// JS Helper: mux.js extraction
window.parseSegmentTimestamps = async (arrayBuffer) => {
    return new Promise((resolve) => {
        const uint8 = new Uint8Array(arrayBuffer);
        const isTs = uint8[0] === 0x47;
        
        let video = { firstPts: null, lastPts: null, firstDts: null, lastDts: null, samples: { pts: [], dts: [] } };
        let audio = { firstPts: null, lastPts: null, firstDts: null, lastDts: null, samples: { pts: [], dts: [] } };
        let foundStreamTypes = new Set();
        
        if (isTs) {
            let scrambledCount = 0;
            
            for (let i = 0; i < uint8.length - 188; i++) {
                if (uint8[i] === 0x47) {
                    const pusi = (uint8[i + 1] & 0x40) !== 0; 
                    const scramblingControl = (uint8[i + 3] >> 6) & 0x03;
                    
                    if (scramblingControl !== 0) {
                        scrambledCount++;
                    }
                    
                    if (pusi && scramblingControl === 0) {
                        const adaptationFieldControl = (uint8[i + 3] >> 4) & 0x03;
                        let payloadOffset = i + 4;
                        
                        if (adaptationFieldControl === 2 || adaptationFieldControl === 3) {
                            const adaptationLength = uint8[payloadOffset];
                            payloadOffset += 1 + adaptationLength;
                        }
                        
                        if (payloadOffset < i + 188 - 6) { 
                            if (uint8[payloadOffset] === 0x00 && uint8[payloadOffset + 1] === 0x00 && uint8[payloadOffset + 2] === 0x01) {
                                const streamId = uint8[payloadOffset + 3];
                                let target = null;
                                
                                if (streamId >= 0xE0 && streamId <= 0xEF) target = video;
                                else if (streamId >= 0xC0 && streamId <= 0xDF) target = audio;
                                
                                if (target) {
                                    foundStreamTypes.add(streamId);
                                    const ptsDtsIndicator = (uint8[payloadOffset + 7] >> 6) & 0x03;
                                    
                                    if (ptsDtsIndicator === 2 || ptsDtsIndicator === 3) {
                                        let pts = ((uint8[payloadOffset + 9] & 0x0E) * 536870912) +
                                                  ((uint8[payloadOffset + 10] & 0xFF) * 2097152) +
                                                  ((uint8[payloadOffset + 11] & 0xFE) * 16384) +
                                                  ((uint8[payloadOffset + 12] & 0xFF) * 128) +
                                                  ((uint8[payloadOffset + 13] & 0xFE) / 2);
                                        
                                        const ptsSeconds = pts / 90000;
                                        if (target.firstPts === null || ptsSeconds < target.firstPts) target.firstPts = ptsSeconds;
                                        if (target.lastPts === null || ptsSeconds > target.lastPts) target.lastPts = ptsSeconds;
                                        target.samples.pts.push(ptsSeconds);
                                        
                                        if (ptsDtsIndicator === 3) {
                                            let dts_val = ((uint8[payloadOffset + 14] & 0x0E) * 536870912) +
                                                          ((uint8[payloadOffset + 15] & 0xFF) * 2097152) +
                                                          ((uint8[payloadOffset + 16] & 0xFE) * 16384) +
                                                          ((uint8[payloadOffset + 17] & 0xFF) * 128) +
                                                          ((uint8[payloadOffset + 18] & 0xFE) / 2);
                                            const dtsSeconds = dts_val / 90000;
                                            if (target.firstDts === null || dtsSeconds < target.firstDts) target.firstDts = dtsSeconds;
                                            if (target.lastDts === null || dtsSeconds > target.lastDts) target.lastDts = dtsSeconds;
                                            target.samples.dts.push(dtsSeconds);
                                        } else {
                                            if (target.firstDts === null || ptsSeconds < target.firstDts) target.firstDts = ptsSeconds;
                                            if (target.lastDts === null || ptsSeconds > target.lastDts) target.lastDts = ptsSeconds;
                                            target.samples.dts.push(ptsSeconds);
                                        }
                                    }
                                }
                            }
                        }
                    }
                    i += 187;
                }
            }
            
            if (scrambledCount > 0) {
                window.addLog(`[!] 패킷 암호화 블록 감지! 타임스탬프 추출 불가.`, "error");
            }
        } else {
            try {
                const dts = muxjs.mp4.Probe.findFirstDts(uint8);
                if (typeof dts === 'number' && dts !== -1 && !isNaN(dts)) {
                    video.firstDts = dts / 90000;
                    video.firstPts = video.firstDts; 
                }
            } catch(e) {
                console.error("fMP4 Probe Error:", e);
            }
        }
        
        // v2.1: Aresample 분석용 세그먼트 내 오디오 통계 계산
        if (audio.samples.pts.length >= 2) {
            const sorted = [...audio.samples.pts].sort((a, b) => a - b);
            audio.actualDuration = sorted[sorted.length - 1] - sorted[0];
            const intervals = [];
            for (let k = 1; k < sorted.length; k++) {
                intervals.push(sorted[k] - sorted[k - 1]);
            }
            const mean = intervals.reduce((s, v) => s + v, 0) / intervals.length;
            audio.avgInterval = mean;
            const variance = intervals.reduce((s, v) => s + (v - mean) ** 2, 0) / intervals.length;
            audio.intervalStdDev = Math.sqrt(variance);
        } else {
            audio.actualDuration = 0;
            audio.avgInterval = 0;
            audio.intervalStdDev = 0;
        }

        if (video.samples.pts.length >= 2) {
            const sorted = [...video.samples.pts].sort((a, b) => a - b);
            video.actualDuration = sorted[sorted.length - 1] - sorted[0];
        } else {
            video.actualDuration = 0;
        }

        resolve({
            video,
            audio,
            hasVideo: video.firstPts !== null,
            hasAudio: audio.firstPts !== null
        });
    });
};

window.addLog = (msg, type) => {
    const out = document.getElementById('log-content');
    const entry = document.createElement('div');
    entry.className = 'log-entry' + (type ? ' log-' + type : '');
    entry.innerHTML = msg;
    out.appendChild(entry);
    const container = document.getElementById('output-container');
    container.scrollTop = container.scrollHeight;
};

window.updateProgress = (percent) => {
    document.getElementById('progress-bar').style.width = percent + '%';
};

window.renderSegmentChart = (canvasId, videoSamples, audioSamples) => {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    const v_pts = (videoSamples && videoSamples.pts) ? videoSamples.pts : [];
    const v_dts = (videoSamples && videoSamples.dts) ? videoSamples.dts : [];
    const a_pts = (audioSamples && audioSamples.pts) ? audioSamples.pts : [];
    const a_dts = (audioSamples && audioSamples.dts) ? audioSamples.dts : [];

    // 세그먼트 내 최소 PTS를 찾아 0점 기준으로 삼음
    const allPts = [...v_pts, ...a_pts];
    const minPts = allPts.length > 0 ? Math.min(...allPts) : 0;

    const mapToData = (ptsArray) => ptsArray.map(p => ({ x: p - minPts, y: p - minPts }));
    const mapToDataDts = (dtsArray) => dtsArray.map(d => ({ x: d - minPts, y: d - minPts }));

    const createDataset = (label, data, color) => ({
        label: label,
        data: data,
        borderColor: color,
        borderWidth: 1.5,
        pointRadius: 1, // 포인트를 살짝 보여줌
        fill: false,
        tension: 0
    });

    try {
        new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [
                    createDataset('Video PTS', mapToData(v_pts), '#38bdf8'),
                    createDataset('Video DTS', mapToDataDts(v_dts), '#818cf8'),
                    createDataset('Audio PTS', mapToData(a_pts), '#22c55e'),
                    createDataset('Audio DTS', mapToDataDts(a_dts), '#f59e0b')
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { 
                        type: 'linear',
                        display: true,
                        title: { display: true, text: 'Time in Segment (s)', color: '#94a3b8', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    },
                    y: { 
                        display: true,
                        title: { display: true, text: 'Relative PTS (s)', color: '#94a3b8', font: { size: 10 } },
                        ticks: { color: '#94a3b8', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { boxWidth: 12, color: '#f1f5f9', font: { size: 10 } }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                },
                animation: false
            }
        });
    } catch (e) {
        console.error("Chart rendering error:", e);
    }
};
