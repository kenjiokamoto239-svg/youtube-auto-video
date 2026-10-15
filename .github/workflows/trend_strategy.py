import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests


ROOT = Path.cwd()
WORK = ROOT / "work"
DATA = ROOT / "data"

WORK.mkdir(exist_ok=True)

PLAN_FILE = WORK / "trend_plan.json"
ANALYTICS_FILE = DATA / "analytics_feedback.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AutoJapaneseShorts/1.0)"
}

GENRES = {
    "人間関係・心理": [
        "心理", "人間関係", "友達", "恋愛", "信頼",
        "会話", "孤独", "性格", "本音", "人間"
    ],
    "お金・仕事の現実": [
        "お金", "給料", "賃金", "仕事", "会社",
        "節約", "貯金", "投資", "物価", "経済",
        "税金", "家計"
    ],
    "習慣・自己啓発": [
        "習慣", "努力", "成功", "勉強", "時間",
        "集中", "継続", "成長", "やる気", "人生"
    ],
    "健康・ランニング": [
        "健康", "運動", "ランニング", "睡眠",
        "食事", "疲労", "筋トレ", "体力"
    ],
    "意外な事実・雑学": [
        "なぜ", "理由", "科学", "歴史", "実は",
        "仕組み", "謎", "意外", "世界", "日本"
    ],
    "ニュース・社会問題": [
        "ニュース", "政府", "政治", "社会", "事件",
        "制度", "法律", "岡山", "介護", "戦争",
        "選挙"
    ],
}


def clean(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def load_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return default


def fetch_feed(url, limit=20):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        items = []

        for entry in feed.entries[:limit]:
            title = clean(entry.get("title", ""))

            if not title:
                continue

            items.append({
                "title": title,
                "summary": clean(
                    entry.get("summary", "")
                )[:500],
                "link": str(entry.get("link", "")),
            })

        return items

    except Exception as exc:
        print("FEED WARNING:", str(exc)[:200])
        return []


def normalize(text):
    return re.sub(
        r"[^一-龯ぁ-んァ-ンa-zA-Z0-9]",
        "",
        str(text or "")
    ).lower()


def genre_for(text):
    scores = {}

    for genre, keywords in GENRES.items():
        scores[genre] = sum(
            1 for word in keywords
            if word.lower() in text.lower()
        )

    best = max(scores, key=scores.get)

    if scores[best] == 0:
        return "意外な事実・雑学"

    return best


def main():
    analytics = load_json(
        ANALYTICS_FILE,
        {}
    )

    candidates = []

    # 1. Google Trendsの日本向け情報
    trends = fetch_feed(
        "https://trends.google.com/trending/rss?geo=JP",
        25
    )

    for item in trends:
        candidates.append({
            **item,
            "source": "Google Trends",
            "genre": genre_for(
                item["title"] + " " + item["summary"]
            ),
        })

    # 2. Googleニュースの最新情報
    news_query = (
        "(日本 OR 世界) "
        "(話題 OR 注目 OR 問題 OR 変化)"
    )

    news_url = (
        "https://news.google.com/rss/search?q="
        + quote(news_query, safe="")
        + "&hl=ja&gl=JP&ceid=JP:ja"
    )

    news = fetch_feed(news_url, 25)

    for item in news:
        candidates.append({
            **item,
            "source": "Google News",
            "genre": genre_for(
                item["title"] + " " + item["summary"]
            ),
        })

    # 3. トレンド情報が取得できない場合の候補
    evergreen = [
        (
            "人間関係・心理",
            "なぜ人は正しい助言より、自分を肯定する言葉を選ぶのか"
        ),
        (
            "お金・仕事の現実",
            "努力しても給料が上がらないとき、確認すべきこと"
        ),
        (
            "習慣・自己啓発",
            "やる気に頼る習慣が長続きしない理由"
        ),
        (
            "健康・ランニング",
            "運動を始めた人が頑張りすぎてしまう理由"
        ),
        (
            "意外な事実・雑学",
            "身近な思い込みを疑うと見えてくること"
        ),
        (
            "ニュース・社会問題",
            "社会の変化が日常生活に与える影響"
        ),
    ]

    for genre, topic in evergreen:
        candidates.append({
            "title": topic,
            "summary": "",
            "link": "",
            "source": "Evergreen fallback",
            "genre": genre,
        })

    # 4. 同じ候補をまとめる
    unique = {}
    for item in candidates:
        key = normalize(item["title"])

        if key and key not in unique:
            unique[key] = item

    candidates = list(unique.values())

    # 5. 過去の動画実績からジャンル別の参考点を計算
    # 累計再生数なので、公開後の経過時間の違いには注意する
    genre_performance = {
        genre: 0.0 for genre in GENRES
    }

    videos = analytics.get(
        "top_videos_by_lifetime_views",
        []
    )

    videos = sorted(
        videos,
        key=lambda item: int(item.get("views", 0)),
        reverse=True
    )[:15]

    for rank, video in enumerate(videos):
        title = clean(video.get("title", ""))
        views = max(
            0,
            int(video.get("views", 0) or 0)
        )

        genre = genre_for(title)

        genre_performance[genre] += (
            views ** 0.5
        ) / (rank + 2)

    # 6. 候補を採点する
    for item in candidates:
        score = 0.0

        if item["source"] == "Google Trends":
            score += 5.0

        elif item["source"] == "Google News":
            score += 2.5

        else:
            score += 0.5

        score += min(
            4.0,
            genre_performance.get(
                item["genre"], 0.0
            ) / 10.0
        )

        if len(item["title"]) >= 9:
            score += 0.5

        if item["source"] == "Google News":
            if item["summary"]:
                score += 0.75

        item["score"] = round(score, 3)

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    selected = candidates[0]

    topic = selected["title"]

    # 短い検索語しかない場合は、解説テーマに変換
    if (
        selected["source"] == "Google Trends"
        and len(topic) < 18
    ):
        topic = (
            f"{topic}は、なぜ今注目されているのか"
        )

    plan = {
        "selected_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S%z"
        ),
        "genre": selected["genre"],
        "topic": topic,
        "trend_source": selected["source"],
        "source_summary": selected["summary"],
        "source_url": selected["link"],
        "selection_score": selected["score"],
        "candidate_count": len(candidates),
        "top_candidates": [
            {
                "topic": item["title"],
                "genre": item["genre"],
                "source": item["source"],
                "score": item["score"],
            }
            for item in candidates[:10]
        ],
        "selection_note": (
            "スコアは候補を絞るための目安です。"
            "再生数を保証するものではありません。"
        ),
    }

    PLAN_FILE.write_text(
        json.dumps(
            plan,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        "TREND PLAN:",
        json.dumps(plan, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
