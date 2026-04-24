// ═══════════════════════════════════════════════════════════════
//  TRADING LOUNGE — Naxi Radio streaming player
//  Tasteful background music for the trading platform.
//  All streams served from Naxi CDN (verified URLs fetched
//  from their public pages — public streams, free to listen).
// ═══════════════════════════════════════════════════════════════
(function() {
    'use strict';

    // ─── Verified stream URLs (Naxi Radio public streams) ─────────────
    const CHANNELS = [
        { id: 'house',   name: 'House',       emoji: '🎛️', url: 'https://naxidigital-house128ssl.streaming.rs:8002/;stream.nsv',   desc: 'Upbeat, focus trading' },
        { id: 'lounge',  name: 'Lounge',      emoji: '🥃', url: 'https://naxidigital-lounge128ssl.streaming.rs:8252/;stream.nsv',  desc: 'Sophisticated, easy' },
        { id: 'chill',   name: 'Chill',       emoji: '🌊', url: 'https://naxidigital-chill128ssl.streaming.rs:8412/;stream.nsv',   desc: 'Relaxed, drawdown mode' },
        { id: 'jazz',    name: 'Jazz',        emoji: '🎷', url: 'https://naxidigital-jazz128ssl.streaming.rs:8172/;stream.nsv',    desc: 'Classy, hotel-lobby' },
        { id: 'rnb',     name: 'R&B',         emoji: '🎤', url: 'https://naxidigital-rnb128ssl.streaming.rs:8122/;stream.nsv',     desc: 'Smooth vibes' },
        { id: 'classic', name: 'Classical',   emoji: '🎻', url: 'https://naxidigital-classic128ssl.streaming.rs:8032/;stream.nsv', desc: 'Deep focus' },
        { id: 'funk',    name: 'Funk',        emoji: '🕺', url: 'https://naxidigital-funk128ssl.streaming.rs:8362/;stream.nsv',    desc: 'High-energy runs' },
        { id: 'clubbing',name: 'Clubbing',    emoji: '🪩', url: 'https://naxidigital-clubbing128ssl.streaming.rs:8092/;stream.nsv',desc: 'Club energy, late session' },
        { id: 'dance',   name: 'Dance',       emoji: '💃', url: 'https://naxidigital-dance128ssl.streaming.rs:8112/;stream.nsv',   desc: 'Momentum & pump runs' },
    ];

    const STORAGE_KEY = 'aw_lounge_prefs_v1';

    // ─── State ───────────────────────────────────────────────────────
    let currentIdx = 0;
    let isPlaying  = false;
    let isLoading  = false;

    // ─── DOM refs ────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);
    const lounge      = $('aw-lounge');
    const pill        = $('aw-lounge-open');
    const panel       = $('aw-lounge-panel');
    const closeBtn    = $('aw-lounge-close');
    const audio       = $('aw-lounge-audio');
    const playBtn     = $('aw-lounge-play');
    const prevBtn     = $('aw-lounge-prev');
    const nextBtn     = $('aw-lounge-next');
    const channelName = $('aw-lounge-channel-name');
    const statusEl    = $('aw-lounge-status');
    const volSlider   = $('aw-lounge-vol');
    const volValue    = $('aw-lounge-vol-value');
    const channelsEl  = $('aw-lounge-channels');

    if (!lounge || !audio) return;  // safety — don't crash if markup missing

    // ─── Persistence ─────────────────────────────────────────────────
    function loadPrefs() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch(_) { return null; }
    }
    function savePrefs() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                channel: CHANNELS[currentIdx].id,
                volume:  parseInt(volSlider.value, 10),
                expanded: lounge.getAttribute('data-state') === 'expanded',
            }));
        } catch(_) {}
    }

    // ─── Channel pill rendering ──────────────────────────────────────
    function renderChannels() {
        channelsEl.innerHTML = CHANNELS.map((c, i) => `
            <button class="aw-lounge-chan ${i === currentIdx ? 'active' : ''}" data-idx="${i}" aria-label="Play ${c.name}">
                <span class="chan-emoji">${c.emoji}</span>
                <span class="chan-name">${c.name}</span>
            </button>
        `).join('');
        channelsEl.querySelectorAll('.aw-lounge-chan').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.getAttribute('data-idx'), 10);
                selectChannel(idx, /*autoPlay*/ true);
            });
        });
    }

    // ─── Core playback ───────────────────────────────────────────────
    function selectChannel(idx, autoPlay) {
        if (idx < 0) idx = CHANNELS.length - 1;
        if (idx >= CHANNELS.length) idx = 0;
        currentIdx = idx;
        const ch = CHANNELS[idx];
        channelName.textContent = ch.name;
        statusEl.textContent = ch.desc;
        // Update active channel highlight
        channelsEl.querySelectorAll('.aw-lounge-chan').forEach((el, i) => {
            el.classList.toggle('active', i === idx);
        });
        // If already playing, switch immediately
        if (isPlaying || autoPlay) {
            audio.src = ch.url;
            play();
        }
        savePrefs();
    }

    function play() {
        setLoading(true);
        audio.volume = (parseInt(volSlider.value, 10) || 0) / 100;
        const p = audio.play();
        if (p && typeof p.then === 'function') {
            p.then(() => {
                setPlaying(true);
                setLoading(false);
                statusEl.textContent = 'Live · streaming';
            }).catch(err => {
                setPlaying(false);
                setLoading(false);
                statusEl.textContent = 'Tap play to start';
                console.warn('[Lounge] play blocked:', err && err.message);
            });
        }
    }

    function pause() {
        audio.pause();
        setPlaying(false);
        statusEl.textContent = 'Paused';
    }

    function setPlaying(v) {
        isPlaying = !!v;
        lounge.classList.toggle('is-playing', isPlaying);
        playBtn.classList.toggle('is-playing', isPlaying);
        playBtn.setAttribute('aria-label', isPlaying ? 'Pause' : 'Play');
    }

    function setLoading(v) {
        isLoading = !!v;
        playBtn.classList.toggle('is-loading', isLoading);
    }

    function togglePlay() {
        if (isLoading) return;
        if (!audio.src) {
            audio.src = CHANNELS[currentIdx].url;
        }
        if (audio.paused) {
            play();
        } else {
            pause();
        }
    }

    // ─── Expand / collapse ───────────────────────────────────────────
    function expand() {
        lounge.setAttribute('data-state', 'expanded');
        savePrefs();
    }
    function collapse() {
        lounge.setAttribute('data-state', 'collapsed');
        savePrefs();
    }

    // ─── Audio events ────────────────────────────────────────────────
    audio.addEventListener('playing', () => { setPlaying(true); setLoading(false); statusEl.textContent = 'Live · streaming'; });
    audio.addEventListener('waiting', () => { setLoading(true); statusEl.textContent = 'Buffering…'; });
    audio.addEventListener('pause',   () => { setPlaying(false); });
    audio.addEventListener('error',   () => {
        setPlaying(false);
        setLoading(false);
        statusEl.textContent = 'Stream unavailable · try another';
    });
    audio.addEventListener('stalled', () => { statusEl.textContent = 'Connection stalled…'; });

    // ─── Wire controls ───────────────────────────────────────────────
    pill.addEventListener('click', expand);
    closeBtn.addEventListener('click', collapse);
    playBtn.addEventListener('click', togglePlay);
    prevBtn.addEventListener('click', () => selectChannel(currentIdx - 1, /*autoPlay*/ isPlaying));
    nextBtn.addEventListener('click', () => selectChannel(currentIdx + 1, /*autoPlay*/ isPlaying));

    volSlider.addEventListener('input', () => {
        const v = parseInt(volSlider.value, 10);
        audio.volume = v / 100;
        volValue.textContent = v;
        savePrefs();
    });

    // Close panel when clicking outside of it
    document.addEventListener('click', (e) => {
        if (lounge.getAttribute('data-state') !== 'expanded') return;
        if (lounge.contains(e.target)) return;
        collapse();
    });

    // Keyboard: space to toggle play when panel has focus
    lounge.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return;  // don't hijack slider
        if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
        if (e.code === 'Escape') collapse();
    });

    // ─── Mobile-data safety: detect metered connection ───────────────
    // Uses Network Information API (Chrome, Edge, Opera, Samsung).
    // Returns true only if we KNOW the connection is metered.
    function isMeteredConnection() {
        try {
            const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
            if (!c) return false;
            // User-declared "save data" flag
            if (c.saveData === true) return true;
            // Cellular = almost certainly metered
            if (c.type === 'cellular') return true;
            // 2G/3G → treat as metered
            if (['slow-2g', '2g', '3g'].includes(c.effectiveType)) return true;
            return false;
        } catch (_) { return false; }
    }

    // Show a one-time advisory on first play over a metered connection.
    function maybeShowDataAdvisory(onConfirm) {
        if (!isMeteredConnection()) { onConfirm(); return; }
        const dismissed = localStorage.getItem('aw_lounge_data_advisory_ok');
        if (dismissed) { onConfirm(); return; }
        // Inline advisory in the status line
        const prevStatus = statusEl.textContent;
        statusEl.innerHTML =
            '<span style="color:#E4C375">Mobile data · ~57 MB/hr</span>' +
            ' · <a href="#" style="color:#4FD1C7;text-decoration:underline" id="aw-lounge-data-ok">Tap here to confirm</a>';
        const ok = document.getElementById('aw-lounge-data-ok');
        if (ok) {
            ok.addEventListener('click', (e) => {
                e.preventDefault();
                try { localStorage.setItem('aw_lounge_data_advisory_ok', '1'); } catch(_){}
                statusEl.textContent = prevStatus;
                onConfirm();
            }, { once: true });
        }
    }

    // Wrap togglePlay to check for mobile data first
    const origTogglePlay = togglePlay;
    togglePlay = function() {
        if (audio.paused) {
            maybeShowDataAdvisory(() => origTogglePlay());
        } else {
            origTogglePlay();
        }
    };
    playBtn.removeEventListener('click', origTogglePlay);
    playBtn.addEventListener('click', togglePlay);

    // ─── Auto-pause when tab hidden for 5+ minutes ───────────────────
    let hiddenAt = 0;
    const IDLE_PAUSE_MS = 5 * 60 * 1000;  // 5 min
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            hiddenAt = Date.now();
        } else if (hiddenAt > 0 && (Date.now() - hiddenAt) > IDLE_PAUSE_MS && isPlaying) {
            pause();
            statusEl.textContent = 'Auto-paused · tab idle 5 min';
        }
    });

    // ─── Bandwidth-info badge in footer ──────────────────────────────
    function addBandwidthBadge() {
        const footer = document.querySelector('.aw-lounge-footer');
        if (!footer || footer.querySelector('.aw-lounge-bw')) return;
        const bw = document.createElement('div');
        bw.className = 'aw-lounge-bw';
        bw.innerHTML = '≈ 57 MB/hr · streams direct from Naxi';
        footer.parentNode.insertBefore(bw, footer);
    }

    // ─── Initialize ──────────────────────────────────────────────────
    function init() {
        renderChannels();
        const prefs = loadPrefs();
        if (prefs) {
            const idx = CHANNELS.findIndex(c => c.id === prefs.channel);
            if (idx >= 0) currentIdx = idx;
            if (typeof prefs.volume === 'number') {
                volSlider.value = prefs.volume;
                volValue.textContent = prefs.volume;
                audio.volume = prefs.volume / 100;
            }
            // Never auto-expand on fresh page load — always start collapsed.
            // We only pre-select the channel so clicking play picks the right one.
        } else {
            volValue.textContent = volSlider.value;
        }
        // Render initial channel name/desc without triggering playback
        const ch = CHANNELS[currentIdx];
        channelName.textContent = ch.name;
        statusEl.textContent = ch.desc;
        channelsEl.querySelectorAll('.aw-lounge-chan').forEach((el, i) => {
            el.classList.toggle('active', i === currentIdx);
        });
        addBandwidthBadge();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
