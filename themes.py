# -*- coding: utf-8 -*-
"""
리포트 디자인 테마.
  · briefing.CSS       → Coinbase 테마(기본, briefing.py 내장)
  · themes.APPLE_CSS   → Apple 테마
상승/하락 색상 구분은 한국 관례(상승 빨강 / 하락 파랑)로 두 테마 공통.
"""

# ══════════════════════════════════════════════════════════════
# Apple 디자인  (SF Pro · 단일 액션블루 · 미니멀 · 넉넉한 여백 · 그림자 없음)
# ══════════════════════════════════════════════════════════════
APPLE_CSS = """
:root{
  --sans:-apple-system,BlinkMacSystemFont,'SF Pro Text','SF Pro Display',system-ui,'Apple SD Gothic Neo','Malgun Gothic',Roboto,Helvetica,Arial,sans-serif;
  --numfont:-apple-system,BlinkMacSystemFont,'SF Pro Text',system-ui,'Malgun Gothic',sans-serif;
  --canvas:#fff;--soft:#f5f5f7;--strong:#f5f5f7;--card:#fff;
  --ink:#1d1d1f;--body:#1d1d1f;--muted:#7a7a7a;--hair:#e0e0e0;--hairsoft:#f0f0f0;
  --primary:#0066cc;--up:#cf202f;--dn:#0066cc;--warn:#e08600;
  --hero:#f5f5f7;--herocard:#fff;--ondark:#1d1d1f;--ondarksoft:#7a7a7a;--herohair:#e0e0e0;
}
@media (prefers-color-scheme:dark){:root{
  --canvas:#000;--soft:#1d1d1f;--strong:#1d1d1f;--card:#161617;
  --ink:#f5f5f7;--body:#f5f5f7;--muted:#86868b;--hair:#2a2a2c;--hairsoft:#242426;
  --primary:#2997ff;--up:#ff5b64;--dn:#2997ff;--warn:#f4b000;
  --hero:#000;--herocard:#1d1d1f;--ondark:#f5f5f7;--ondarksoft:#86868b;--herohair:#2a2a2c;
}}
:root[data-theme=dark]{
  --canvas:#000;--soft:#1d1d1f;--strong:#1d1d1f;--card:#161617;
  --ink:#f5f5f7;--body:#f5f5f7;--muted:#86868b;--hair:#2a2a2c;--hairsoft:#242426;
  --primary:#2997ff;--up:#ff5b64;--dn:#2997ff;--warn:#f4b000;
  --hero:#000;--herocard:#1d1d1f;--ondark:#f5f5f7;--ondarksoft:#86868b;--herohair:#2a2a2c;
}
:root[data-theme=light]{
  --canvas:#fff;--soft:#f5f5f7;--strong:#f5f5f7;--card:#fff;
  --ink:#1d1d1f;--body:#1d1d1f;--muted:#7a7a7a;--hair:#e0e0e0;--hairsoft:#f0f0f0;
  --primary:#0066cc;--up:#cf202f;--dn:#0066cc;--warn:#e08600;
  --hero:#f5f5f7;--herocard:#fff;--ondark:#1d1d1f;--ondarksoft:#7a7a7a;--herohair:#e0e0e0;
}
*{box-sizing:border-box;}
body{margin:0;background:var(--canvas);color:var(--ink);font-family:var(--sans);
font-size:17px;line-height:1.47;letter-spacing:-.01em;-webkit-font-smoothing:antialiased;}
.num{font-family:var(--numfont);font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
.up{color:var(--up);} .dn{color:var(--dn);} .mut{color:var(--muted);} .sep{color:var(--ondarksoft);}

/* Hero — light parchment, big SF Pro Display */
.hero{background:var(--hero);color:var(--ondark);padding:72px 24px 64px;text-align:center;}
.hero-in{max-width:1000px;margin:0 auto;}
.hero .eb{font-size:19px;font-weight:600;letter-spacing:-.01em;color:var(--primary);margin-bottom:10px;}
.hero h1{font-size:56px;font-weight:600;letter-spacing:-.028em;line-height:1.07;margin:0;text-wrap:balance;}
.hero .hsub{color:var(--ondarksoft);font-size:19px;margin:14px 0 34px;font-weight:400;}
.stat-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;text-align:left;}
.scard{background:var(--herocard);border:1px solid var(--herohair);border-radius:18px;padding:22px 24px;}
.scard .sl{font-size:14px;color:var(--ondarksoft);margin-bottom:10px;letter-spacing:-.01em;}
.scard .sv{font-size:28px;font-weight:600;letter-spacing:-.02em;}
.scard .sc{font-size:14px;margin-top:6px;}

.wrap{max-width:1120px;margin:0 auto;padding:8px 24px 80px;}
section{margin-top:64px;}
.eyebrow{display:flex;align-items:baseline;gap:12px;margin-bottom:12px;justify-content:center;text-align:center;flex-wrap:wrap;}
.badge{display:inline-block;font-size:14px;font-weight:600;letter-spacing:-.01em;
color:var(--primary);background:transparent;padding:0;}
.badge-key{color:var(--primary);}
.eyebrow .sub{font-size:15px;color:var(--muted);}
h2{font-size:40px;font-weight:600;letter-spacing:-.02em;line-height:1.1;margin:0 0 22px;color:var(--ink);text-align:center;text-wrap:balance;}

/* 총평 */
.brief{margin-top:44px;}
.ov-card{background:var(--soft);border-radius:18px;padding:28px 32px;font-size:19px;line-height:1.6;color:var(--ink);text-align:center;max-width:900px;margin:0 auto;}
.ov-card p{margin:0;}
.brief-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px;}
.bcard{background:var(--card);border:1px solid var(--hair);border-radius:18px;padding:24px 26px;}
.bh{font-size:14px;font-weight:600;letter-spacing:-.01em;color:var(--muted);margin-bottom:14px;}
ul.cps{margin:0;padding-left:20px;} ul.cps li{margin:9px 0;line-height:1.5;font-size:15px;}
.news-row{padding:11px 0;border-bottom:1px solid var(--hairsoft);}
.news-row:last-child{border-bottom:none;}
.news-t{font-weight:600;font-size:15px;line-height:1.4;}
.news-i{font-size:13.5px;color:var(--muted);margin-top:4px;}
.cal-card{margin-top:16px;}
.cal{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 28px;}
.cal-row{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid var(--hairsoft);font-size:15px;}
.cal-d{font-family:var(--numfont);color:var(--primary);font-weight:600;min-width:100px;}
.cal-e{color:var(--ink);}

.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
.kcard{background:var(--card);border:1px solid var(--hair);border-radius:18px;padding:18px 20px;}
.kl{font-size:14px;color:var(--muted);} .kv{font-size:24px;font-weight:600;margin:6px 0 3px;color:var(--ink);letter-spacing:-.02em;} .kc{font-size:14px;}

.mcap-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px;}
.mcap-card{background:var(--soft);border-radius:18px;padding:22px 24px;}
.mcap-h{font-size:14px;color:var(--muted);}
.mcap-v{font-size:30px;font-weight:600;margin:6px 0 14px;letter-spacing:-.02em;color:var(--ink);}
.mcap-gauge{height:6px;background:var(--hair);border-radius:100px;overflow:hidden;}
.mcap-fill{height:100%;background:var(--primary);border-radius:100px;}
.mcap-fill.warn{background:var(--warn);}
.mcap-lbl{display:flex;justify-content:space-between;font-size:14px;margin-top:9px;color:var(--body);}
.mcap-sub{font-size:12.5px;color:var(--muted);margin-top:5px;}

.money{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px;}
.mcard{background:var(--soft);border-radius:18px;padding:22px 24px;}
.ml{font-size:14px;color:var(--muted);} .mv{font-size:30px;font-weight:600;margin:6px 0 3px;letter-spacing:-.02em;color:var(--ink);} .mc{font-size:14px;}

.table-card{background:var(--card);border:1px solid var(--hair);border-radius:18px;overflow-x:auto;margin-bottom:10px;}
table.scan{width:100%;border-collapse:collapse;font-size:15px;}
table.scan th{text-align:left;padding:15px 20px;font-weight:600;font-size:12.5px;letter-spacing:-.01em;color:var(--muted);border-bottom:1px solid var(--hair);white-space:nowrap;}
table.scan td{padding:14px 20px;border-bottom:1px solid var(--hairsoft);white-space:nowrap;vertical-align:middle;}
table.scan tbody tr:last-child td{border-bottom:none;}
td.nm{font-weight:600;color:var(--ink);} td.r,th.r{text-align:right;}
td.num .up,td.num .dn{font-weight:600;}
td.ar{font-weight:600;font-size:14px;} .a-up{color:var(--up);} .a-dn{color:var(--dn);} .a-y{color:var(--muted);}
td.tags{white-space:normal;line-height:2;}
.tg{display:inline-block;font-size:12px;font-weight:600;padding:3px 11px;border-radius:100px;background:var(--soft);color:var(--muted);margin:1px 3px 1px 0;border:1px solid var(--hair);}
.tg-up{color:var(--up);border-color:var(--up);}
.tg-dn{color:var(--dn);border-color:var(--dn);}
.tg-y{color:var(--warn);border-color:var(--warn);}

.charts{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.charts figure{margin:0;background:#fff;border:1px solid var(--hair);border-radius:18px;padding:10px;}
.charts img{width:100%;display:block;border-radius:10px;}

.rs-wrap{background:var(--card);border:1px solid var(--hair);border-radius:18px;padding:20px 24px;text-align:left;}
.rs-row{display:grid;grid-template-columns:120px 1fr 68px;align-items:center;gap:12px;padding:7px 0;}
.rs-nm{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.rs-track{position:relative;height:16px;background:var(--soft);border-radius:5px;}
.rs-mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--hair);}
.rs-bar{position:absolute;top:1px;bottom:1px;border-radius:4px;}
.rs-bar.rs-right{left:50%;} .rs-bar.rs-left{right:50%;}
.rs-bar.up{background:var(--up);} .rs-bar.dn{background:var(--dn);}
.rs-val{font-size:13px;text-align:right;font-weight:600;}

footer{max-width:1120px;margin:64px auto 0;padding:32px 24px;border-top:1px solid var(--hair);color:var(--muted);font-size:12px;line-height:1.7;text-align:center;}

@media(max-width:820px){
  .hero h1{font-size:36px;} .hero .hsub{font-size:17px;}
  .stat-cards,.kpi{grid-template-columns:repeat(2,1fr);}
  h2{font-size:30px;}
  .brief-grid,.money,.charts,.mcap-grid,.cal{grid-template-columns:1fr;}
}
@media print{
  .hero{padding:40px 24px;} section{margin-top:40px;break-inside:avoid;}
  .table-card,.bcard,.mcap-card,.charts figure{break-inside:avoid;}
}
"""


def get_css(theme, coinbase_css):
    return APPLE_CSS if theme == "apple" else coinbase_css
