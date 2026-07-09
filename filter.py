"""
====================================================================
한국자동차환경협회 뉴스 웹진 - 중복제거 + 부정필터 + 요약 + 통계 (STEP 2)
====================================================================
역할: collect.py 가 만든 data/YYYY-MM-DD.json 을 읽어서,
      ① 중복 기사 제거 (Claude 의미 기반, 카테고리별 1회 호출)
      ② 부정 뉴스 제거 (부정 키워드 1차 + Claude 2차)
      ③ 각 기사 요약 2~3줄 재작성
      ④ 웹진 한 줄 요약 생성
      ⑤ 그날 통계를 stats.json 에 누적 (대시보드용)   ← 이번 추가
      후 data JSON 을 덮어써 저장한다.

통계 누적(stats.json):
  대시보드가 읽을 날짜별 통계를 쌓는다. 매일 한 항목씩 추가(같은 날짜는 갱신).
  담는 값: 수집 수, 중복 제거, 부정 차단(hard/ai), 최종 통과, 카테고리별 통과.
  ※ 누적은 오늘부터 시작되므로, 추이 그래프는 며칠 쌓여야 의미가 생긴다.

API 키:
  - 로컬: .env 의 ANTHROPIC_API_KEY
  - 자동: GitHub Secrets 의 ANTHROPIC_API_KEY

사용법:
  python filter.py            (data 최신 날짜)
  python filter.py 2026-07-08 (특정 날짜)
====================================================================
"""
import os
import sys
import json
import glob

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from negative_keywords import HARD_NEGATIVE, SOFT_NEGATIVE

try:
    from anthropic import Anthropic
except ImportError:
    print("[오류] anthropic 라이브러리가 없습니다: pip install anthropic python-dotenv")
    raise SystemExit(1)

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    print("[오류] Claude API 키가 없습니다.")
    print("  로컬: .env 에 ANTHROPIC_API_KEY=sk-ant-...")
    print("  자동: GitHub Secrets 에 ANTHROPIC_API_KEY 등록")
    raise SystemExit(1)

client = Anthropic(api_key=API_KEY)
MODEL = "claude-haiku-4-5-20251001"

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
STATS_FILE = os.path.join(ROOT, "stats.json")   # 대시보드용 통계 누적 파일


def has_keyword(text, keywords):
    return any(kw in text for kw in keywords)


def dedupe_category(articles):
    """카테고리 내 중복 기사를 Claude로 판정해 제거한다.
    반환: (남긴 기사 리스트, 제거된 개수)"""
    if len(articles) <= 1:
        return articles, 0

    titles_text = "\n".join(f"{i+1}. {a.get('title','')}" for i, a in enumerate(articles))
    prompt = f"""아래는 같은 카테고리로 수집된 뉴스 제목 목록입니다.
같은 사건·내용을 다룬 중복 기사를 찾아 묶어주세요.
표현이 달라도(예: '돌입'='시작'='개시', '합작사'='합작법인') 같은 사건이면 중복입니다.

각 중복 그룹에서는 제목이 가장 완결되고 정보가 풍부한 기사 1건의 번호를 'keep'으로 지정하고,
나머지 중복 번호를 'remove'에 넣으세요. 중복이 없는 기사는 어디에도 넣지 않습니다.

제목 목록:
{titles_text}

아래 JSON 형식으로만 답하세요. 다른 말은 하지 마세요.
{{"groups": [{{"keep": 번호, "remove": [번호, ...]}}, ...]}}
중복이 전혀 없으면 {{"groups": []}} 로 답하세요."""

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
    except Exception as e:
        print(f"    [중복 판정 실패 - 전부 유지] ({e})")
        return articles, 0

    remove_idx = set()
    for grp in result.get("groups", []):
        for n in grp.get("remove", []):
            if isinstance(n, int) and 1 <= n <= len(articles):
                remove_idx.add(n - 1)
    kept = [a for i, a in enumerate(articles) if i not in remove_idx]
    return kept, len(remove_idx)


def judge_and_rewrite(article):
    """Claude 1회 호출로 부정 판정 + 요약 재작성. 반환: (적절여부, 새요약)"""
    title = article.get("title", "")
    summary = article.get("summary", "")
    prompt = f"""당신은 한국자동차환경협회가 회원사에게 보내는 뉴스 웹진의 편집자입니다.
아래 기사가 회원사 대상 뉴스로 적절한지 판단하고, 요약을 다듬어 주세요.

[판단 기준]
- 부적절: 특정 기업/인물의 사고·비리·소송·논란 등 부정적이거나 자극적인 내용
- 적절: 정책, 기술, 산업 동향, 보급 실적 등 중립적이거나 긍정적인 정보성 내용

[요약 기준]
- 2~3문장으로 핵심만 간결하게, 객관적 정보 전달 문체
- 원문에 없는 내용을 지어내지 말 것

기사 제목: {title}
기사 원문 요약: {summary}

아래 JSON 형식으로만 답하세요.
{{"appropriate": true 또는 false, "summary": "다듬은 2~3문장 요약"}}"""
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        return bool(result.get("appropriate", False)), result.get("summary", summary).strip()
    except Exception as e:
        print(f"    [AI 판정 실패 - 원본 유지] {title[:30]}... ({e})")
        return True, summary


def process_category(cat_name, articles):
    """카테고리 하나: 중복 제거 → 부정 필터 + 요약."""
    stats = {"input": len(articles), "dup": 0, "hard": 0, "ai": 0, "kept": 0}
    if not articles:
        print(f"  [{cat_name}] 0건")
        return [], stats

    articles, dup_removed = dedupe_category(articles)
    stats["dup"] = dup_removed

    kept = []
    for art in articles:
        title = art.get("title", "")
        if has_keyword(title, HARD_NEGATIVE):
            stats["hard"] += 1
            continue
        appropriate, new_summary = judge_and_rewrite(art)
        if not appropriate:
            stats["ai"] += 1
            continue
        art["summary"] = new_summary
        kept.append(art)
        stats["kept"] += 1

    print(f"  [{cat_name}] 통과 {len(kept)}건 (중복제거 {stats['dup']}, 부정제외 {stats['hard']+stats['ai']})")
    return kept, stats


def filter_all(cat_dict):
    result = {}
    per_cat = {}   # 카테고리별 통과 수 (대시보드용)
    total = {"input": 0, "dup": 0, "hard": 0, "ai": 0, "kept": 0}
    for cat_name, articles in cat_dict.items():
        kept, stats = process_category(cat_name, articles)
        result[cat_name] = kept
        per_cat[cat_name] = stats["kept"]
        for k in total:
            total[k] += stats[k]
    return result, total, per_cat


def make_edition_summary(daily):
    titles = [arts[0].get("title", "") for arts in daily.values() if arts]
    if not titles:
        return ""
    joined = "\n".join(f"- {t}" for t in titles[:6])
    prompt = f"""아래는 오늘 자동차·환경 뉴스 웹진의 주요 기사 제목들입니다.
이 내용을 대표하는 한 줄 요약을 만들어 주세요.

{joined}

조건:
- 쉼표로 구분된 핵심 키워드 3개 정도 (예: "전기차 보조금 개편, 수소충전소 확대, EU 규제")
- 15자~40자 이내
- 다른 말 없이 요약 문구만 출력"""
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip().strip('"')
    except Exception as e:
        print(f"  [웹진 요약 생성 실패] ({e})")
        return ""


def update_stats(date_str, total_d, total_g, per_cat_d):
    """그날 통계를 stats.json 에 누적한다 (같은 날짜는 갱신).
    대시보드가 이 파일을 읽어 오늘 통계·추이 그래프를 그린다."""
    # 국내+해외 합산
    collected = total_d["input"] + total_g["input"]
    dup = total_d["dup"] + total_g["dup"]
    hard = total_d["hard"] + total_g["hard"]
    ai = total_d["ai"] + total_g["ai"]
    kept = total_d["kept"] + total_g["kept"]

    entry = {
        "date": date_str,
        "collected": collected,
        "duplicates_removed": dup,
        "negative_blocked": hard + ai,
        "hard_blocked": hard,
        "ai_blocked": ai,
        "final_published": kept,
        "by_category": per_cat_d,   # 국내 카테고리별 통과 수
    }

    # 기존 통계 로드
    stats = []
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except Exception:
            stats = []

    # 같은 날짜 제거 후 추가 (덮어쓰기), 날짜순 정렬
    stats = [s for s in stats if s.get("date") != date_str]
    stats.append(entry)
    stats.sort(key=lambda s: s.get("date", ""))

    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return entry


def main():
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
        if not files:
            print("[오류] data 폴더에 JSON 파일이 없습니다. collect.py 를 먼저 실행하세요.")
            sys.exit(1)
        date_str = os.path.basename(files[-1]).replace(".json", "")

    data_path = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(data_path):
        print(f"[오류] 데이터 파일이 없습니다: {data_path}")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"중복제거 + 부정필터 + 요약 + 통계: {date_str}")
    print("=" * 50)

    print("[국내 뉴스]")
    daily, total_d, per_cat_d = filter_all(data.get("daily", {}))

    print("\n[해외 뉴스]")
    global_news, total_g, _ = filter_all(data.get("global", {}))

    print("\n[웹진 한 줄 요약]")
    edition_summary = make_edition_summary(daily)
    print(f"  요약: {edition_summary}")

    data["daily"] = daily
    data["global"] = global_news
    data["summary"] = edition_summary

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 통계 누적 (대시보드용)
    entry = update_stats(date_str, total_d, total_g, per_cat_d)

    print("\n" + "=" * 50)
    print(f"완료: data/{date_str}.json 갱신 + stats.json 누적")
    print(f"  수집 {entry['collected']}건 → 중복제거 {entry['duplicates_removed']}, "
          f"부정차단 {entry['negative_blocked']}, 최종 {entry['final_published']}건")


if __name__ == "__main__":
    main()
