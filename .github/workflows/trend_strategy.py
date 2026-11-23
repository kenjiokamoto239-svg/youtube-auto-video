import json, math, re, statistics, time, unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

ROOT = Path.cwd()
WORK, DATA = ROOT / "work", ROOT / "data"
WORK.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)
PLAN_FILE = WORK / "trend_plan.json"
HISTORY_FILE = WORK / "topic_history.json"
ANALYTICS_FILE = DATA / "analytics_feedback.json"
JST = timezone(timedelta(hours=9))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AutoJapaneseShorts/2.0)"}

GENRE_RULES = {
    "エンタメ・ゲーム": [
        "アニメ", "漫画", "マンガ", "ゲーム", "ポケモン", "マインクラフト",
        "minecraft", "ドラゴンクエスト", "ドラクエ", "ゼルダ", "ティアキン",
        "ワンピース", "サンジ", "ちいかわ", "ちびまる子", "名探偵コナン",
        "コナン", "usj", "ユニバーサル", "ディズニー", "テーマパーク",
        "モンスト", "無職転生", "ジョジョ", "wii sports", "マリオ", "鬼滅",
        "naruto", "ナルト", "声優", "俳優", "歌手", "アイドル", "芸能",
        "映画", "ドラマ", "音楽", "ライブ", "コラボ", "宮野真守", "早見沙織",
        "YOSHIKI", "嵐", "NiziU", "HANA", "ラウール", "snow man",
        "alan walker", "ミュージックステーション", "mステ"
    ],
    "人間関係・心理": [
        "心理", "人間関係", "友達", "恋愛", "信頼", "会話", "孤独",
        "性格", "本音", "第一印象", "コミュニケーション", "カップル",
        "デート", "スマホ"
    ],
    "お金・仕事の現実": [
        "お金", "給料", "賃金", "仕事", "会社", "節約", "貯金", "投資",
        "物価", "経済", "税金", "家計", "介護", "社会保障"
    ],
    "習慣・自己啓発": [
        "習慣", "努力", "成功", "勉強", "時間", "集中", "継続", "成長",
        "やる気", "人生", "先延ばし"
    ],
    "健康・ランニング": [
        "健康", "運動", "ランニング", "睡眠", "食事", "疲労", "筋トレ",
        "体力", "栄養", "ビタミン", "塩分", "血圧", "食欲", "動物",
        "生き物", "犬", "猫", "タコ", "ミツバチ"
    ],
    "ニュース・社会問題": [
        "ニュース", "政府", "政治", "社会", "事件", "制度", "法律",
        "岡山", "戦争", "選挙"
    ],
    "意外な事実・雑学": [
        "なぜ", "理由", "科学", "歴史", "実は", "仕組み", "謎", "意外",
        "世界", "日本"
    ],
}


def clean(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def normalize(value):
    value = unicodedata.normalize("NFKC", clean(value)).lower()
    return re.sub(r"[^一-龯ぁ-んァ-ンa-z0-9]", "", value)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def parse_date(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ジャンル判定の補完
GENRE_RULES["エンタメ・ゲーム"] = list(dict.fromkeys(
    GENRE_RULES.get("エンタメ・ゲーム", [])
    + ["テレビ", "番組", "放送", "タレント", "芸能人", "バラエティ"]
))

GENRE_RULES["ニュース・社会問題"] = list(dict.fromkeys(
    GENRE_RULES.get("ニュース・社会問題", [])
    + ["復興", "防災", "地域", "災害", "火災", "避難", "消防", "被災", "復旧"]
))

GENRE_RULES["健康・ランニング"] = [
    word for word in GENRE_RULES.get("健康・ランニング", [])
    if word not in {"動物", "生き物", "犬", "猫", "タコ", "ミツバチ"}
]

GENRE_RULES["健康・ランニング"] = list(dict.fromkeys(
    GENRE_RULES["健康・ランニング"]
    + ["感染", "ウイルス", "ワクチン", "医療", "病気",
       "鳥インフルエンザ", "殺処分", "養鶏"]
))

GENRE_RULES["動物・生き物"] = [
    "動物", "生き物", "犬", "猫", "タコ", "ミツバチ",
    "鳥", "昆虫", "深海生物", "恐竜", "魚",
    "クジラ", "イルカ", "ニワトリ", "養鶏"
]

GENRE_RULES["スポーツ・競技"] = [
    "スポーツ", "サッカー", "野球", "バスケットボール",
    "バスケ", "テニス", "陸上", "マラソン", "選手",
    "チーム", "リーグ", "試合", "監督", "移籍",
    "得点", "ゴール", "優勝", "プロ野球", "Jリーグ",
    "NBA", "F1", "日本代表", "阪神", "大谷翔平"
]


def genre_for(text):
    value = clean(text).lower()

    # これらの言葉だけではジャンルを決めない
    generic_terms = {
        "なぜ", "理由", "実は", "仕組み",
        "謎", "意外", "世界", "日本"
    }

    scores = {
        genre: sum(
            1 + min(len(word), 12) / 12
            for word in words
            if word.lower() not in generic_terms
            and word.lower() in value
        )
        for genre, words in GENRE_RULES.items()
    }

    best = max(scores, key=scores.get)

    # 分類できないテーマは不明として返す
    return best if scores[best] > 0 else None


def channel_performance():
    data = load_json(ANALYTICS_FILE, {})
    snapshot = parse_date(
        data.get("updated_at_jst")
    ) or datetime.now(JST)

    if (
        datetime.now(JST) - snapshot
    ).total_seconds() > 7 * 86400:
        print(
            "CHANNEL ANALYTICS STALE: "
            "performance weighting skipped"
        )
        return {}, 0, None

    rates = {}
    all_rates = []

    for video in data.get("all_videos", []):
        try:
            duration = int(
                video.get("duration_seconds")
            )
            views = int(
                video.get("views")
            )
        except (TypeError, ValueError):
            continue

        if duration <= 0 or duration > 59 or views < 0:
            continue

        published = parse_date(
            video.get("published_at")
        )

        if not published:
            continue

        raw_age = (
            snapshot - published.astimezone(JST)
        ).total_seconds() / 3600

        if raw_age < 0:
            continue

        vph = views / max(12.0, raw_age)

        genre = genre_for(
            video.get("title", "")
        )

        # 分類できた動画だけジャンル別実績に使う
        if genre:
            rates.setdefault(genre, []).append(vph)

        # 全体中央値には分類できない動画も含める
        all_rates.append(vph)

    if not all_rates:
        return {}, 0, None

    global_median = statistics.median(all_rates)

    result = {}

    for genre, values in rates.items():
        smoothed = (
            sum(values) + global_median * 2
        ) / (len(values) + 2)

        # 3本未満のジャンルは加点しない
        if len(values) >= 3 and global_median > 0:
            relative = (
                smoothed / max(global_median, 0.1)
            )

            bonus = max(
                -0.8,
                min(
                    0.8,
                    math.log(max(relative, 0.1)) * 0.5
                )
            )
        else:
            bonus = 0.0

        result[genre] = {
            "sample_count": len(values),
            "median_vph": round(
                statistics.median(values), 2
            ),
            "bonus": round(bonus, 3)
        }

    return result, len(all_rates), global_median


def fetch_feed(url, limit=20):
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                wait = 2 ** (attempt + 1)
                print("FEED RETRY:", response.status_code, attempt + 1, wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            return [
                {
                    "title": clean(e.get("title", "")),
                    "summary": clean(e.get("summary", ""))[:900],
                    "link": str(e.get("link", "")),
                    "published_at": (
                        datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                        if e.get("published_parsed") else ""
                    )
                }
                for e in feed.entries[:limit] if clean(e.get("title", ""))
            ]
        except Exception as error:
            print("FEED WARNING:", str(error)[:200])
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return []


def is_recent(title, recent_keys):
    key = normalize(title)
    for old in recent_keys:
        if not key or not old:
            continue
        if key in old or old in key or SequenceMatcher(None, key, old).ratio() >= 0.82:
            return True
    return False


def main():
    performance, shorts_count, global_median = channel_performance()
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []

    candidates = {}

    def add(item, source):
        title = clean(item.get("title", ""))
        key = normalize(title)
        published_at = parse_date(item.get("published_at"))
        if published_at and (datetime.now(JST) - published_at.astimezone(JST)).total_seconds() > 7 * 86400:
            return
        if len(title) < 3 or not key:
            return
        candidate = {
            "title": title,
            "summary": clean(item.get("summary", ""))[:900],
            "link": str(item.get("link", "") or "").strip(),
            "published_at": item.get("published_at", ""),
            "source": source,
            "genre": genre_for(title + " " + clean(item.get("summary", "")))
        }
        old = candidates.get(key)
        if old is None or len(candidate["summary"]) > len(old["summary"]):
            candidates[key] = candidate

    trends = fetch_feed("https://trends.google.com/trending/rss?geo=JP", 30)
    for item in trends:
        add(item, "Google Trends")
    print("GOOGLE TRENDS ITEMS:", len(trends))

    terms = [x["title"] for x in trends[:3] if len(x["title"]) >= 2]
    if not terms:
        print("GOOGLE TRENDS: no terms; evergreen fallback will be used")

    news_count = 0
    for term in terms:
        url = (
            "https://news.google.com/rss/search?q="
            + quote(term + " ニュース", safe="")
            + "&hl=ja&gl=JP&ceid=JP:ja"
        )
        items = fetch_feed(url, 15)
        news_count += len(items)
        for item in items:
            add(item, "Google News")
    print("GOOGLE NEWS ITEMS:", news_count)

    evergreen = [
        ("エンタメ・ゲーム", "ゲームの隠し要素を見つけたくなる理由"),
        ("エンタメ・ゲーム", "アニメの名場面が記憶に残る演出の仕組み"),
        ("健康・ランニング", "睡眠不足が食欲に影響する仕組み"),
        ("人間関係・心理", "初対面の会話で相手の名前が印象に残る理由"),
        ("意外な事実・雑学", "猫が高い場所を好む理由"),
        ("お金・仕事の現実", "給料明細で見落としやすい項目"),
        ("ニュース・社会問題", "介護現場の人手不足を減らす取り組み")
    ]
    for genre, topic in evergreen:
        add({"title": topic}, "Evergreen fallback")
        candidates[normalize(topic)]["genre"] = genre

    all_candidates = list(candidates.values())
    recent_keys = [
        normalize(x.get("topic", ""))
        for x in history[-14:] if isinstance(x, dict)
    ]
    available = [x for x in all_candidates if not is_recent(x["title"], recent_keys)]
    if not available:
        print("TOPIC HISTORY WARNING: recent candidates exhausted; reuse allowed")
        available = all_candidates

    for item in available:
        score = 4.5 if item["source"] == "Google News" else (
            4.0 if item["source"] == "Google Trends" else 0.5
        )
        if len(item["summary"]) >= 80:
            score += 0.75
        if item["link"]:
            score += 0.25
        if 8 <= len(item["title"]) <= 55:
            score += 0.25

        genre_data = performance.get(item["genre"], {})
        bonus = float(genre_data.get("bonus", 0))
        item["channel_performance_bonus"] = round(bonus, 3)
        item["genre_sample_count"] = int(genre_data.get("sample_count", 0))
        item["genre_median_vph"] = genre_data.get("median_vph")
        item["score"] = round(score + bonus, 3)

    available.sort(key=lambda x: x["score"], reverse=True)
    if not available:
        raise RuntimeError("動画テーマ候補を取得できませんでした。")

    selected = available[0]
    topic = selected["title"]
    if selected["source"] == "Google Trends" and len(topic) < 18:
        topic += "が今話題の理由"

    now = datetime.now(JST)
    history.append({"topic": topic, "date": now.isoformat(timespec="seconds")})
    HISTORY_FILE.write_text(
        json.dumps(history[-300:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    plan = {
        "selected_at": now.isoformat(timespec="seconds"),
        "genre": selected["genre"],
        "topic": topic,
        "trend_source": selected["source"],
        "source_summary": selected["summary"],
        "source_url": selected["link"],
        "selection_score": selected["score"],
        "candidate_count": len(all_candidates),
        "eligible_candidate_count": len(available),
        "channel_performance": {
            "shorts_sample_count": shorts_count,
            "global_median_views_per_hour": round(global_median, 2) if global_median is not None else None,
            "genre_sample_count": selected["genre_sample_count"],
            "genre_median_views_per_hour": selected["genre_median_vph"],
            "genre_bonus": selected["channel_performance_bonus"]
        },
        "top_candidates": [
            {
                "topic": x["title"], "genre": x["genre"], "source": x["source"],
                "score": x["score"], "source_url": x["link"],
                "published_at": x["published_at"],
                "summary": x["summary"][:300],
                "channel_sample_count": x["genre_sample_count"],
                "genre_median_vph": x["genre_median_vph"]
            }
            for x in available[:10]
        ],
        "selection_note": (
            "Google Trends・Google Newsの日本語候補を優先。"
            "直近50本以内のShortsだけを公開後経過時間で補正して採点。"
            "長尺動画はShorts実績に混ぜず、直近14テーマの重複を避ける。"
            "スコアは候補選定の目安であり、再生数を保証しない。"
        )
    }
    PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TREND PLAN:", json.dumps(plan, ensure_ascii=False))
    print("TOPIC STRATEGY: trends + channel Shorts performance")
    print("VIDEO GENRE:", selected["genre"])
    print("VIDEO TOPIC:", topic)
    print("TREND SOURCE:", selected["source"])
    print("TREND SCORE:", selected["score"])
    print("SHORTS PERFORMANCE SAMPLE:", shorts_count)
    print("TOPIC HISTORY SAVED:", len(history))


if __name__ == "__main__":
    main()
