"""
====================================================================
한국자동차환경협회 뉴스 웹진 - 중복제거 + 부정필터 + 요약 (STEP 2)
====================================================================
역할: collect.py 가 만든 data/YYYY-MM-DD.json 을 읽어서,
      ① 중복 기사 제거 (Claude 의미 기반, 카테고리별 1회 호출)
      ② 부정 뉴스 제거 (부정 키워드 1차 + Claude 2차)
      ③ 각 기사 요약을 2~3줄로 재작성
      ④ 웹진 한 줄 요약 생성
      후 같은 파일에 덮어써 저장한다.

처리 순서 (비용 최적):
  중복 제거를 먼저 → 중복 기사를 요약에 안 보내 비용 절감.

중복 판정 방식 (방법 B):
  같은 사건을 다룬 기사는 제목 표현이 달라도(돌입=시작=개시) 하나로 묶어야 한다.
  단순 단어 비교로는 안 되므로 Claude가 의미로 판정한다.
  카테고리별로 제목 목록을 한 번에 보내 "중복 그룹"을 받고,
  각 그룹에서 정보가 가장 온전한 기사 1건만 남긴다.

API 키:
  - 로컬: .env 의 ANTHROPIC_API_KEY
  - 자동: GitHub Secrets 의 ANTHROPIC_API_KEY

라이브러리:
  pip install anthropic python-dotenv

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


def has_keyword(text, keywords):
    return any(kw in text for kw in keywords)


def dedupe_category(articles):
    """카테고리 내 중복 기사를 Claude로 판정해 제거한다.
    같은 사건이면 제목 표현이 달라도 하나로 묶고, 정보가 온전한 1건만 남긴다.
    반환: (남긴 기사 리스트, 제거된 개수)"""
    if len(articles) <= 1:
        return articles, 0

    # 제목 목록을 번호와 함께 Claude에 전달
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
            model=MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
    except Exception as e:
        # 판정 실패 시 안전하게 전부 유지 (중복 제거 안 함)
        print(f"    [중복 판정 실패 - 전부 유지] ({e})")
        return articles, 0

    # remove로 지정된 번호(1-based)를 제거
    remove_idx = set()
    for grp in result.get("groups", []):
        for n in grp.get("remove", []):
            if isinstance(n, int) and 1 <= n <= len(articles):
                remove_idx.add(n - 1)

    kept = [a for i, a in enumerate(articles) if i not in remove_idx]
    return kept, len(remove_idx)


def judge_and_rewrite(article):
    """Claude 1회 호출로 부정 판정 + 요약 재작성.
    반환: (적절여부, 새요약)"""
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
            model=MODEL,
            max_tokens=500,
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
    stats = {"dup": 0, "hard": 0, "ai": 0, "kept": 0}
    if not articles:
        print(f"  [{cat_name}] 0건")
        return [], stats

    # ① 중복 제거 (먼저)
    articles, dup_removed = dedupe_category(articles)
    stats["dup"] = dup_removed

    # ② 부정 필터 + 요약
    kept = []
    for art in articles:
        title = art.get("title", "")
        if has_keyword(title, HARD_NEGATIVE):      # 1차: 명백한 부정어 즉시 제외
            stats["hard"] += 1
            continue
        appropriate, new_summary = judge_and_rewrite(art)   # 2차: Claude
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
    total = {"dup": 0, "hard": 0, "ai": 0, "kept": 0}
    for cat_name, articles in cat_dict.items():
        kept, stats = process_category(cat_name, articles)
        result[cat_name] = kept
        for k in total:
            total[k] += stats[k]
    return result, total


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

    print(f"중복제거 + 부정필터 + 요약 시작: {date_str}")
    print("=" * 50)

    print("[국내 뉴스]")
    daily, stat_d = filter_all(data.get("daily", {}))

    print("\n[해외 뉴스]")
    global_news, stat_g = filter_all(data.get("global", {}))

    print("\n[웹진 한 줄 요약]")
    edition_summary = make_edition_summary(daily)
    print(f"  요약: {edition_summary}")

    data["daily"] = daily
    data["global"] = global_news
    data["summary"] = edition_summary

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"완료: data/{date_str}.json 갱신")
    print(f"  중복 제거: {stat_d['dup'] + stat_g['dup']}건")
    print(f"  부정 제외: {stat_d['hard']+stat_d['ai']+stat_g['hard']+stat_g['ai']}건")
    print(f"  최종 통과: {stat_d['kept'] + stat_g['kept']}건")


if __name__ == "__main__":
    main()
