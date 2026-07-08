"""
====================================================================
한국자동차환경협회 뉴스 웹진 - 부정 뉴스 필터링 + 요약 (STEP 2)
====================================================================
역할: collect.py 가 만든 data/YYYY-MM-DD.json 을 읽어서,
      ① 부정 뉴스를 걸러내고
      ② 각 기사 요약을 매끄러운 2~3줄로 다시 쓰고
      ③ 그날 웹진의 한 줄 요약을 만든 뒤
      같은 파일에 덮어써서 저장한다.
      이 필터링된 JSON을 STEP 3(generate.py)이 읽어 웹진을 만든다.

필터링 방식 (하이브리드):
  1차 - 부정 키워드로 분리 (negative_keywords.py)
        · HARD_NEGATIVE: 제목에 있으면 바로 제외 (AI 호출 안 함 → 비용 절약)
        · SOFT_NEGATIVE: 제목에 있으면 AI 2차 판정으로
        · 둘 다 없으면 '긍정 후보'로 통과 (단, 요약 재작성은 함)
  2차 - Claude Haiku 가 톤을 판정 + 요약 재작성 (한 번의 호출로 함께 처리)

주의:
  - Claude API 키는 코드에 직접 쓰지 않는다.
      · 로컬 실행: 같은 폴더의 .env 파일에서 ANTHROPIC_API_KEY 읽기
      · 자동 실행: GitHub Secrets 에 ANTHROPIC_API_KEY 등록
  - 크레딧이 없으면 API 호출이 실패한다 (콘솔 Billing에서 크레딧 확인).

로컬 준비물:
  - .env 파일에 아래 줄 추가 (기존 네이버 키와 함께):
      ANTHROPIC_API_KEY=sk-ant-...(발급받은 키)

라이브러리 설치 (터미널에서 한 번):
  pip install anthropic python-dotenv

사용법:
  python filter.py            (data 폴더의 최신 날짜 파일 처리)
  python filter.py 2026-07-08 (특정 날짜 지정)
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

# --------------------------------------------------------------------
# Claude API 준비
# --------------------------------------------------------------------
try:
    from anthropic import Anthropic
except ImportError:
    print("[오류] anthropic 라이브러리가 없습니다. 터미널에서 설치하세요:")
    print("  pip install anthropic python-dotenv")
    raise SystemExit(1)

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    print("[오류] Claude API 키가 없습니다.")
    print("  로컬: .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 를 넣으세요.")
    print("  자동 실행: GitHub Secrets에 ANTHROPIC_API_KEY 를 등록하세요.")
    raise SystemExit(1)

client = Anthropic(api_key=API_KEY)

# 사용할 모델: Haiku (빠르고 저렴, 필터링·요약에 충분)
MODEL = "claude-haiku-4-5-20251001"

# --------------------------------------------------------------------
# 경로
# --------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")


def has_keyword(text, keywords):
    """text 안에 keywords 중 하나라도 있으면 True."""
    return any(kw in text for kw in keywords)


def judge_and_rewrite(article):
    """Claude Haiku 한 번 호출로 두 가지를 함께 처리:
      1) 이 기사가 회원사 대상으로 적절한지(부정/자극적이지 않은지) 판정
      2) 요약을 매끄러운 2~3줄로 다시 쓰기
    반환: (통과여부: bool, 새요약: str)
    """
    title = article.get("title", "")
    summary = article.get("summary", "")

    # Claude에게 JSON으로만 답하도록 지시 (파싱 쉽게)
    prompt = f"""당신은 한국자동차환경협회가 회원사에게 보내는 뉴스 웹진의 편집자입니다.
아래 기사가 회원사 대상 뉴스로 적절한지 판단하고, 요약을 다듬어 주세요.

[판단 기준]
- 부적절: 특정 기업/인물에 대한 사고·비리·소송·논란 등 부정적이거나 자극적인 내용
- 적절: 정책, 기술, 산업 동향, 보급 실적 등 중립적이거나 긍정적인 정보성 내용

[요약 작성 기준]
- 2~3문장으로 핵심만 간결하게
- 객관적이고 정보 전달 위주의 문체
- 원문에 없는 내용을 지어내지 말 것

기사 제목: {title}
기사 원문 요약: {summary}

아래 JSON 형식으로만 답하세요. 다른 말은 하지 마세요.
{{"appropriate": true 또는 false, "summary": "다듬은 2~3문장 요약"}}"""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # 혹시 ```json 같은 코드펜스가 붙으면 제거
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        appropriate = bool(result.get("appropriate", False))
        new_summary = result.get("summary", summary).strip()
        return appropriate, new_summary
    except Exception as e:
        # AI 호출 실패 시: 안전하게 '통과'시키되 원본 요약 유지
        # (필터가 실패했다고 뉴스를 통째로 버리지 않기 위함)
        print(f"    [AI 판정 실패 - 원본 유지] {title[:30]}... ({e})")
        return True, summary


def filter_category(cat_dict):
    """카테고리별로 부정 필터 + 요약 재작성."""
    result = {}
    stats = {"hard_cut": 0, "ai_cut": 0, "kept": 0}

    for cat_name, articles in cat_dict.items():
        kept = []
        for art in articles:
            title = art.get("title", "")

            # 1차: HARD 부정어 → 바로 제외 (AI 호출 안 함)
            if has_keyword(title, HARD_NEGATIVE):
                stats["hard_cut"] += 1
                continue

            # 2차: Claude 판정 + 요약 재작성
            #   (SOFT 부정어가 있든 없든, 통과 후보는 요약을 다듬는다)
            appropriate, new_summary = judge_and_rewrite(art)
            if not appropriate:
                stats["ai_cut"] += 1
                continue

            art["summary"] = new_summary
            kept.append(art)
            stats["kept"] += 1

        result[cat_name] = kept
        print(f"  [{cat_name}] 통과 {len(kept)}건")

    return result, stats


def make_edition_summary(daily):
    """그날 주요 기사들로 웹진 한 줄 요약을 만든다 (Claude 1회 호출)."""
    # 각 카테고리 첫 기사 제목을 모아 재료로 사용
    titles = []
    for cat_name, articles in daily.items():
        if articles:
            titles.append(articles[0].get("title", ""))
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
            model=MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip().strip('"')
    except Exception as e:
        print(f"  [웹진 요약 생성 실패 - 빈 값] ({e})")
        return ""


def main():
    # 대상 날짜 결정
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
        if not files:
            print("[오류] data 폴더에 JSON 파일이 없습니다. 먼저 collect.py 를 실행하세요.")
            sys.exit(1)
        date_str = os.path.basename(files[-1]).replace(".json", "")

    data_path = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(data_path):
        print(f"[오류] 데이터 파일이 없습니다: {data_path}")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"부정 뉴스 필터링 + 요약 시작: {date_str}")
    print("=" * 50)

    print("[국내 뉴스 필터링]")
    daily, stats_d = filter_category(data.get("daily", {}))

    print("\n[해외 뉴스 필터링]")
    global_news, stats_g = filter_category(data.get("global", {}))

    print("\n[웹진 한 줄 요약 생성]")
    edition_summary = make_edition_summary(daily)
    print(f"  요약: {edition_summary}")

    # 결과를 같은 파일에 덮어쓰기
    data["daily"] = daily
    data["global"] = global_news
    data["summary"] = edition_summary

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"필터링 완료: data/{date_str}.json 갱신")
    print(f"  1차 제외(명백한 부정어): {stats_d['hard_cut'] + stats_g['hard_cut']}건")
    print(f"  2차 제외(AI 부적절 판정): {stats_d['ai_cut'] + stats_g['ai_cut']}건")
    print(f"  최종 통과: {stats_d['kept'] + stats_g['kept']}건")
    print("이제 generate.py 를 실행하면 필터링된 뉴스로 웹진이 만들어집니다.")


if __name__ == "__main__":
    main()
