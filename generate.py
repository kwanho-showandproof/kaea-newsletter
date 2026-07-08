"""
====================================================================
한국자동차환경협회 뉴스 웹진 - HTML 생성기 (STEP 3)
====================================================================
역할: 하루치 뉴스 데이터(JSON)를 받아서 웹진 HTML을 자동 생성한다.

생성물:
  1) news/YYYY-MM-DD.html  → 그날의 웹진 (날짜별 영구 보관본)
  2) index.html            → 오늘의 웹진 (데일리/해외/이전뉴스 3탭)
  3) archive.json          → 지난 발송 목록 (이전 뉴스 탭이 이 목록을 읽음)

핵심 흐름:
  - data/YYYY-MM-DD.json 을 읽는다 (STEP 1·2가 만들어 줄 파일)
  - 날짜별 HTML을 만든다
  - archive.json 목록에 오늘 항목을 추가한다 (이관 기능)
  - index.html 을 다시 만든다 (오늘 데이터 + 이전 뉴스 목록)

사용법:
  python generate.py 2026-06-18
  (날짜를 안 주면 data 폴더에서 가장 최신 날짜를 자동 선택)
====================================================================
"""
import json
import os
import sys
import glob
import html

# --------------------------------------------------------------------
# 경로 설정 - 이 스크립트 파일이 있는 폴더를 기준으로 잡는다
# --------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")      # 뉴스 데이터 JSON 폴더
NEWS_DIR = os.path.join(ROOT, "news")      # 날짜별 웹진 HTML 폴더
ARCHIVE_FILE = os.path.join(ROOT, "archive.json")  # 지난 발송 목록
INDEX_FILE = os.path.join(ROOT, "index.html")

os.makedirs(NEWS_DIR, exist_ok=True)

# --------------------------------------------------------------------
# 카테고리 표시 순서 (협회 실제 메일 기준 6종)
# 데이터에 이 순서대로 없어도, 아래 순서로 화면에 배치한다
# --------------------------------------------------------------------
DAILY_ORDER = [
    "상위기관 뉴스",
    "배출 저감사업 뉴스",
    "전기·수소차 뉴스",
    "회원사 뉴스",
    "한국자동차환경협회 뉴스",
    "기타 뉴스",
]
GLOBAL_ORDER = ["유럽 (EU)", "미국 (USA)", "중국 (China)", "글로벌 종합"]

# --------------------------------------------------------------------
# 공통 CSS (index / 날짜별 페이지 공용)
# --------------------------------------------------------------------
CSS = """
  :root {
    --primary: #1F4E79; --primary-dark: #163C5E; --primary-light: #E6F1FB;
    --accent: #2E75B6; --text: #1A1A1A; --text-sub: #555; --text-mute: #888;
    --border: #E5E5E5; --bg: #F8F9FB; --card: #FFFFFF;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; font-size: 14px; }
  .webzine-header { background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    color: white; padding: 28px 32px 22px; text-align: center; }
  .webzine-brand { font-size: 13px; letter-spacing: 2px; opacity: 0.85; margin-bottom: 6px; font-weight: 500; }
  .webzine-title { font-size: 28px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.5px; }
  .webzine-sub { font-size: 14px; opacity: 0.9; margin: 0; }
  .webzine-date { margin-top: 14px; font-size: 12px; opacity: 0.75; }
  .member-notice { background: var(--primary-light); border-bottom: 1px solid var(--border);
    padding: 10px 32px; font-size: 12px; color: var(--primary); text-align: center; }
  main { max-width: 800px; margin: 0 auto; padding: 28px 24px 40px; }
  .cat-section { margin-bottom: 32px; }
  .cat-header { background: var(--primary); color: white; padding: 14px 22px; font-size: 16px;
    font-weight: 700; border-radius: 6px 6px 0 0; letter-spacing: -0.3px; }
  .cat-body { background: var(--card); border: 1px solid var(--border); border-top: none;
    border-radius: 0 0 6px 6px; padding: 6px 0; }
  .news-item { padding: 18px 22px; border-bottom: 1px solid #F0F0F0; }
  .news-item:last-child { border-bottom: none; }
  .news-title { font-size: 16px; font-weight: 700; margin: 0 0 8px; line-height: 1.4; }
  .news-title a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
  .news-title a:hover { color: var(--primary); }
  .news-source { font-size: 12.5px; font-weight: 600; color: var(--text); background: #F5F5F5;
    padding: 2px 6px; border-radius: 3px; margin-right: 4px; }
  .news-summary { font-size: 14px; color: var(--text-sub); margin: 0; line-height: 1.65; }
  .footer { background: var(--card); border-top: 1px solid var(--border); padding: 24px 32px;
    text-align: center; font-size: 12px; color: var(--text-mute); line-height: 1.7; margin-top: 40px; }
  .footer strong { color: var(--text-sub); }
"""

# CSS 중 index 전용 추가분 (탭, 검색, 아카이브 목록)
INDEX_EXTRA_CSS = """
  .tabs { background: var(--card); border-bottom: 2px solid var(--border); padding: 0;
    display: flex; justify-content: center; gap: 0; }
  .tab { padding: 16px 28px; cursor: pointer; font-size: 15px; color: var(--text-sub);
    border-bottom: 3px solid transparent; transition: all 0.15s; font-weight: 500; }
  .tab:hover { color: var(--primary); background: var(--primary-light); }
  .tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 700; background: var(--primary-light); }
  .page { display: none; }
  .page.active { display: block; }
  .info-box { background: var(--primary-light); border-left: 4px solid var(--primary); padding: 14px 18px;
    border-radius: 4px; font-size: 13px; color: #0C2C4A; margin-bottom: 22px; line-height: 1.6; }
  .info-box strong { color: var(--primary); }
  .archive-search { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px; margin-bottom: 18px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  .search-label { font-size: 13px; color: var(--text-sub); font-weight: 500; }
  .search-input { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px;
    font-family: inherit; flex: 1; min-width: 200px; }
  .search-select { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px;
    font-family: inherit; background: var(--card); }
  .search-btn { padding: 8px 16px; background: var(--primary); color: white; border: none;
    border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; }
  .search-btn:hover { background: var(--primary-dark); }
  .archive-row { display: grid; grid-template-columns: 110px 1fr 80px; gap: 16px; align-items: center;
    padding: 14px 18px; background: var(--card); border: 1px solid var(--border); border-radius: 6px;
    margin-bottom: 8px; font-size: 13.5px; transition: border-color 0.15s; }
  .archive-row:hover { border-color: var(--accent); background: #FAFCFE; }
  .archive-date { font-weight: 700; color: var(--primary); font-size: 13px; }
  .archive-title { font-weight: 500; color: var(--text); }
  .archive-link { color: var(--accent); font-weight: 600; text-align: right; font-size: 13px;
    text-decoration: none; cursor: pointer; background: none; border: none; font-family: inherit; padding: 0; }
  .archive-link:hover { text-decoration: underline; }
  .footer-links { margin-top: 10px; font-size: 11.5px; }
  .footer-links a { color: var(--text-mute); text-decoration: none; margin: 0 6px; cursor: pointer; }
  .footer-links a:hover { color: var(--primary); text-decoration: underline; }
"""

# 날짜별 페이지 전용 추가분 (돌아가기 바)
EDITION_EXTRA_CSS = """
  .back-bar { background: var(--card); border-bottom: 1px solid var(--border); padding: 12px 32px; }
  .back-link { color: var(--accent); font-size: 13px; font-weight: 600; text-decoration: none; cursor: pointer; }
  .back-link:hover { text-decoration: underline; }
  .archive-badge { display: inline-block; background: var(--primary-light); color: var(--primary);
    font-size: 11px; padding: 3px 10px; border-radius: 12px; margin-left: 8px; font-weight: 600; }
"""


def esc(text):
    """HTML 특수문자를 안전하게 처리한다 (실제 뉴스 제목에 <, >, & 등이 있을 수 있음)"""
    return html.escape(str(text), quote=True)


def fmt_date_kr(date_str, dow):
    """2026-06-18 → 2026년 6월 18일 (목)"""
    y, m, d = date_str.split("-")
    return f"{y}년 {int(m)}월 {int(d)}일 ({dow})"


def build_news_items(items):
    """뉴스 항목 리스트 → HTML 조각.
    url이 있으면 실제 원문 링크, 없으면 데모용 안내(openArticle)로 처리한다."""
    out = ""
    for i, it in enumerate(items, 1):
        title = esc(it.get("title", ""))
        source = esc(it.get("source", ""))
        date = esc(it.get("date", ""))
        summary = esc(it.get("summary", ""))
        url = it.get("url", "").strip()
        # 발행사(source)는 네이버 API가 제공하지 않으므로 날짜만 표시한다.
        # 날짜가 있으면 [7.7], 없으면 라벨 자체를 생략.
        src_label = f"[{date}]" if date else ""

        if url:
            # 실제 원문 링크 (새 창) - 진짜 URL이라 iframe 튕김 이슈 없음
            link = f'<a href="{esc(url)}" target="_blank" rel="noopener">{i}. {title}</a>'
        else:
            # URL이 없는 경우 데모 안내
            link = f'<a onclick="openArticle(event)">{i}. {title}</a>'

        # 날짜 라벨이 있을 때만 source span을 넣는다 (빈 대괄호 방지)
        source_html = f'<span class="news-source">{src_label}</span> ' if src_label else ""
        out += f"""      <div class="news-item">
        <div class="news-title">{link}</div>
        <p class="news-summary">{source_html}{summary}</p>
      </div>
"""
    return out


def build_cat_sections(cats_dict, order):
    """카테고리 딕셔너리 → 카테고리별 섹션 HTML.
    order 순서대로 배치하되, 항목이 없는 카테고리는 건너뛴다."""
    out = ""
    # 먼저 정해진 순서대로
    seen = set()
    for cat_name in order:
        items = cats_dict.get(cat_name)
        if not items:
            continue
        seen.add(cat_name)
        out += f"""  <div class="cat-section">
    <div class="cat-header">{esc(cat_name)}</div>
    <div class="cat-body">
{build_news_items(items)}    </div>
  </div>
"""
    # order에 없는 카테고리가 데이터에 있으면 뒤에 추가 (누락 방지)
    for cat_name, items in cats_dict.items():
        if cat_name in seen or not items:
            continue
        out += f"""  <div class="cat-section">
    <div class="cat-header">{esc(cat_name)}</div>
    <div class="cat-body">
{build_news_items(items)}    </div>
  </div>
"""
    return out


def build_edition_page(ed):
    """날짜별 웹진 (단일 페이지, 탭 없음). '오늘 웹진으로 돌아가기' 링크 포함."""
    date_kr = fmt_date_kr(ed["date"], ed["dow"])
    daily_sections = build_cat_sections(ed["daily"], DAILY_ORDER)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>자동차 환경 데일리 제{esc(ed['no'])}호 · {esc(ed['date'])}</title>
<style>{CSS}{EDITION_EXTRA_CSS}</style>
</head>
<body>

<header class="webzine-header">
  <div class="webzine-brand">KAAEA NEWSLETTER</div>
  <h1 class="webzine-title">자동차 환경 데일리</h1>
  <p class="webzine-sub">한국자동차환경협회 회원사 뉴스 웹진</p>
  <div class="webzine-date">{esc(date_kr)} · 제 {esc(ed['no'])}호</div>
</header>

<div class="back-bar">
  <a class="back-link" href="../index.html">← 오늘의 웹진으로 돌아가기</a>
  <span class="archive-badge">지난 뉴스 · 제{esc(ed['no'])}호</span>
</div>

<div class="member-notice">
  본 자료는 {esc(ed['date'])} 발송된 웹진 원본입니다.
</div>

<main>
{daily_sections}</main>

<footer class="footer">
  <strong>한국자동차환경협회 (KAAEA)</strong><br>
  본 뉴스 웹진은 협회 회원사를 위한 일일 모니터링 서비스입니다.<br>
  본 자료의 무단 복제·배포를 금합니다.
</footer>

<script>
  function openArticle(e) {{
    if (e && e.preventDefault) e.preventDefault();
    alert('이 기사는 원문 링크가 아직 연결되지 않았습니다.');
    return false;
  }}
</script>

</body>
</html>
"""


def build_index(today, archive_list):
    """index.html (3탭: 데일리 / 해외 / 이전뉴스). 열람 버튼은 실제 날짜별 파일로 이동."""
    date_kr = fmt_date_kr(today["date"], today["dow"])
    daily_sections = build_cat_sections(today["daily"], DAILY_ORDER)
    global_sections = build_cat_sections(today.get("global", {}), GLOBAL_ORDER)

    # 이전 뉴스 목록: archive_list 는 최신순 정렬된 리스트
    archive_rows = ""
    for a in archive_list:
        date_dot = a["date"].replace("-", ".")
        archive_rows += f"""  <div class="archive-row">
    <div class="archive-date">{esc(date_dot)}</div>
    <div class="archive-title">제 {esc(a['no'])}호 · {esc(a['summary'])}</div>
    <div><button class="archive-link" onclick="openEdition('{esc(a['date'])}')">열람 →</button></div>
  </div>
"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>한국자동차환경협회 뉴스 웹진</title>
<style>{CSS}{INDEX_EXTRA_CSS}</style>
</head>
<body>

<header class="webzine-header">
  <div class="webzine-brand">KAAEA NEWSLETTER</div>
  <h1 class="webzine-title">자동차 환경 데일리</h1>
  <p class="webzine-sub">한국자동차환경협회 회원사 뉴스 웹진</p>
  <div class="webzine-date">{esc(date_kr)} · 제 {esc(today['no'])}호</div>
</header>

<div class="member-notice">
  본 웹진은 한국자동차환경협회 회원사를 위한 뉴스 모니터링 서비스입니다.
</div>

<nav class="tabs">
  <div class="tab active" onclick="go('daily')">데일리 모니터링</div>
  <div class="tab" onclick="go('global')">해외뉴스 모니터링</div>
  <div class="tab" onclick="go('archive')">이전 뉴스 보기</div>
</nav>

<main>

<section class="page active" id="daily">
{daily_sections}</section>

<section class="page" id="global">
  <div class="info-box">
    <strong>해외뉴스 모니터링 안내</strong> · EU·미국·중국 등 주요국의 자동차 환경 정책과 글로벌 시장 동향을 별도로 모아 정리한 섹션입니다. 매일 데일리 모니터링과 함께 갱신됩니다.
  </div>
{global_sections}</section>

<section class="page" id="archive">
  <div class="info-box">
    <strong>이전 뉴스 보기</strong> · 과거 발송된 뉴스 웹진을 날짜별로 조회하실 수 있습니다. 열람 버튼을 누르면 해당 날짜의 웹진 페이지로 이동합니다. 회원사는 언제든 지난 자료를 자유롭게 열람할 수 있습니다.
  </div>

  <div class="archive-search">
    <span class="search-label">검색</span>
    <input type="text" class="search-input" placeholder="키워드로 검색 (예: 전기차 보조금)">
    <select class="search-select">
      <option>전체 카테고리</option>
      <option>상위기관 뉴스</option>
      <option>배출 저감사업 뉴스</option>
      <option>전기·수소차 뉴스</option>
      <option>회원사 뉴스</option>
      <option>한국자동차환경협회 뉴스</option>
      <option>기타 뉴스</option>
    </select>
    <button class="search-btn">검색</button>
  </div>

{archive_rows}
  <div style="text-align: center; margin-top: 22px;">
    <button class="search-btn" style="background: var(--card); color: var(--primary); border: 1px solid var(--primary);">더 이전 자료 보기</button>
  </div>
</section>

</main>

<footer class="footer">
  <strong>한국자동차환경협회 (KAAEA)</strong><br>
  본 뉴스 웹진은 협회 회원사를 위한 일일 모니터링 서비스로, 매일 오전 자동 갱신됩니다.<br>
  본 자료의 무단 복제·배포를 금합니다.
  <div class="footer-links">
    <a onclick="return false;">협회 공식 홈페이지</a> ·
    <a onclick="return false;">회원사 문의</a> ·
    <a onclick="return false;">수신거부</a>
  </div>
</footer>

<script>
  function go(id) {{
    document.querySelectorAll('.page').forEach(function(p) {{ p.classList.remove('active'); }});
    document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.getElementById(id).classList.add('active');
    var tabs = document.querySelectorAll('.tab');
    var ids = ['daily', 'global', 'archive'];
    var idx = ids.indexOf(id);
    if (idx >= 0) tabs[idx].classList.add('active');
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
  }}

  function openEdition(date) {{
    window.location.href = 'news/' + date + '.html';
  }}

  function openArticle(e) {{
    if (e && e.preventDefault) e.preventDefault();
    alert('이 기사는 원문 링크가 아직 연결되지 않았습니다.');
    return false;
  }}
</script>

</body>
</html>
"""


def update_archive(ed):
    """archive.json 을 갱신한다 (이관 기능의 핵심).
    같은 날짜가 이미 있으면 갱신, 없으면 추가. 최신순 정렬해서 저장."""
    archive = []
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            archive = json.load(f)

    # 오늘 항목
    entry = {"no": ed["no"], "date": ed["date"], "summary": ed.get("summary", "")}

    # 같은 날짜 제거 후 추가 (중복 방지)
    archive = [a for a in archive if a["date"] != ed["date"]]
    archive.append(entry)

    # 날짜 최신순 정렬
    archive.sort(key=lambda a: a["date"], reverse=True)

    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    return archive


def main():
    # 1) 대상 날짜 결정 (인자로 받거나, data 폴더 최신 파일 자동 선택)
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
        if not files:
            print("[오류] data 폴더에 JSON 파일이 없습니다.")
            sys.exit(1)
        date_str = os.path.basename(files[-1]).replace(".json", "")

    data_path = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(data_path):
        print(f"[오류] 데이터 파일이 없습니다: {data_path}")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        ed = json.load(f)

    print(f"[1/4] 데이터 로드: {date_str} 제{ed['no']}호")

    # 2) 날짜별 웹진 파일 생성
    edition_html = build_edition_page(ed)
    edition_path = os.path.join(NEWS_DIR, f"{date_str}.html")
    with open(edition_path, "w", encoding="utf-8") as f:
        f.write(edition_html)
    print(f"[2/4] 날짜별 웹진 생성: news/{date_str}.html ({len(edition_html):,} bytes)")

    # 3) archive.json 갱신 (이관)
    archive = update_archive(ed)
    print(f"[3/4] 이전 뉴스 목록 갱신: 총 {len(archive)}건")

    # 4) index.html 재생성
    index_html = build_index(ed, archive)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"[4/4] index.html 재생성 완료 ({len(index_html):,} bytes)")

    print(f"\n완료: {date_str} 웹진 생성 및 이전 뉴스 이관 완료")


if __name__ == "__main__":
    main()
