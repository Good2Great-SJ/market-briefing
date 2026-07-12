-- state.db (git에 커밋됨, 민감정보 없음)
CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    blog_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    raw_content TEXT,
    summary TEXT,
    keywords TEXT,
    status TEXT NOT NULL DEFAULT 'collected',
    collected_at TEXT NOT NULL,
    notified_at TEXT
);

-- 증권사 리포트 원자료 (종목당 리포트 1건 = 1행)
CREATE TABLE IF NOT EXISTS consensus_reports (
    nid TEXT PRIMARY KEY,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    broker TEXT NOT NULL,
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    target_price INTEGER,
    opinion_raw TEXT,
    fiscal_year_current TEXT,
    revenue_estimate_current REAL,
    operating_profit_estimate_current REAL,
    fiscal_year_next TEXT,
    revenue_estimate_next REAL,
    operating_profit_estimate_next REAL,
    estimate_unit TEXT,
    pdf_status TEXT NOT NULL DEFAULT 'unknown',
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consensus_reports_stock
    ON consensus_reports (stock_code, report_date);

-- 브로커별 최신 상태 (목표가/의견 변동 감지의 기준값)
CREATE TABLE IF NOT EXISTS consensus_state (
    stock_code TEXT NOT NULL,
    broker TEXT NOT NULL,
    target_price INTEGER,
    opinion_raw TEXT,
    stance TEXT,
    last_report_date TEXT,
    last_nid TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (stock_code, broker)
);

-- 워치리스트 종목별 최초 백필(6개월 bootstrap) 완료 여부
CREATE TABLE IF NOT EXISTS consensus_watchlist_state (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT NOT NULL,
    bootstrapped_at TEXT
);

-- 일일 체크 멱등성 마커 (하루 1회만 실행되도록)
CREATE TABLE IF NOT EXISTS consensus_run_log (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_run_date TEXT
);

-- 종목별 마지막 발송 시점의 컨센서스 요약값 (다음 업데이트와 비교해 상향/하향 판단에 사용)
CREATE TABLE IF NOT EXISTS consensus_snapshot_state (
    stock_code TEXT PRIMARY KEY,
    avg_target_price REAL,
    margin_current REAL,
    margin_next REAL,
    optimistic INTEGER,
    neutral INTEGER,
    pessimistic INTEGER,
    updated_at TEXT NOT NULL
);
