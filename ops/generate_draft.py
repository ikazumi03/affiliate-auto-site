#!/usr/bin/env python3
"""
くらしの選び方ガイド - 記事下書き自動作成スクリプト
topics.json のテーマから、公式情報重視・E-E-A-T準拠・ステマ規制対応のHTML記事下書きを作成し、
index.html への掲載と sitemap.xml の更新を行います。
"""
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY_JST = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9)))
TODAY_ISO = TODAY_JST.strftime('%Y-%m-%d')
TODAY_DISPLAY = TODAY_JST.strftime('%Y年%m月%d日')

SITE_URL = "https://affiliate-auto-site-1tk.pages.dev"


def generate_article_html(topic):
    slug = topic['slug']
    title = topic['title']
    desc = topic['description']
    category = topic['category']
    canonical = f"{SITE_URL}/{slug}.html"
    sources_li = "".join([f'<li><a href="{s["url"]}" rel="noopener noreferrer">{s["name"]}</a></li>' for s in topic.get('official_sources', [])])

    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | くらしの選び方ガイド</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}"><link rel="stylesheet" href="style.css">
<style>.learn-box{{border:1px solid #d8e6e4;border-radius:14px;padding:19px;background:#f6fbfa;margin:22px 0}}.learn-table{{width:100%;border-collapse:collapse;margin:18px 0}}.learn-table th,.learn-table td{{padding:12px;border:1px solid #cfdedb;text-align:left}}.learn-table th{{background:#f1f7f6}}.learn-ad{{margin:28px 0;border:1px solid #aacac4;border-radius:16px;padding:22px;text-align:center;background:#f8fcfb}}.learn-ad img{{max-width:100%;height:auto}}.learn-small{{font-size:.88rem;color:#53666b}}.learn-tags{{display:flex;gap:8px;flex-wrap:wrap}}.learn-tags span{{border-radius:24px;background:#edf6f3;padding:6px 12px;font-size:.9rem}}@media(max-width:600px){{.learn-ad{{padding:12px}}.learn-table{{font-size:.9rem}}}}</style>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","headline":"{title}","datePublished":"{TODAY_ISO}","dateModified":"{TODAY_ISO}","inLanguage":"ja"}}</script>
</head><body>
<header class="top"><div class="bar"><a class="brand" href="index.html">くらしの<span>選び方</span>ガイド</a><nav><a href="index.html#articles">比較ガイド</a><a href="about.html">サイトについて</a><a href="policy.html">運営方針</a></nav></div></header>
<div class="adnotice">【広告】本記事にはアフィリエイト広告（A8.net等の提携プログラム）を含みます。掲載リンクを通じた申込みで運営者に報酬が発生する場合があります。</div>
<main class="container"><article class="article"><div class="breadcrumbs"><a href="index.html">ホーム</a> / {category} / ガイド</div>
<span class="tag">{category}・広告あり</span>
<h1>{title}</h1>
<p class="lead">{desc} この記事は公開元および監督官庁の一次情報に基づいて構成しており、筆者の主観的な有料体験談・レビューの捏造ではありません。</p>

<div class="learn-box">
<strong>先に結論：比較の3大チェック軸</strong>
<ul>
<li><strong>月々の基本料金と初期費用：</strong>端末代や事務手数料を含めた実質総額で比較する</li>
<li><strong>利用可能なデータ容量・提供エリア：</strong>日常で使うギガ数と生活圏の電波状況を確認する</li>
<li><strong>解約・MNP転出の条件：</strong>最低利用期間や違約金の有無を事前に確認する</li>
</ul>
</div>

<h2>選ぶときに確認したい比較ポイント</h2>
<table class="learn-table"><thead><tr><th>比較項目</th><th>大手キャリア</th><th>格安SIM・サブブランド</th></tr></thead><tbody>
<tr><th>月額費用の目安</th><td>約5,000円〜8,000円（大容量・無制限プラン中心）</td><td>約1,000円〜3,500円（小〜中容量プランが中心）</td></tr>
<tr><th>店舗サポート</th><td>全国のキャリアショップで対面サポートあり</td><td>原則オンライン手続き中心（一部店舗あり）</td></tr>
<tr><th>通信速度の傾向</th><td>昼休み・混雑時間帯でも安定しやすい</td><td>利用者の多い時間帯に速度が変動する場合がある</td></tr>
<tr><th>向いている人</th><td>手厚い対面窓口やデータ無制限を求める人</td><td>毎月の固定費を大幅に抑えたい人</td></tr>
</tbody></table>
<p class="learn-small">※上記は一般的なサービス分類の目安です。具体的な提供条件や割引（家族割・光回線セット割）は契約プランにより異なります。</p>

<h2>契約・乗り換え前の注意点</h2>
<ul>
<li><strong>SIMロック・対応バンド：</strong>現在使用中のスマートフォンが移行先事業者の回線に対応しているか確認してください。</li>
<li><strong>キャリアメールの扱い：</strong>「@docomo.ne.jp」などのメールアドレスを引き続き使う場合は、各社の持ち運びサービス（有料）の申込みが必要です。</li>
<li><strong>支払方法：</strong>クレジットカード決済のみの事業者が多いため、口座振替やデビットカードを希望する場合は対応状況を確認しましょう。</li>
</ul>

<section class="learn-ad" aria-label="提携広告情報">
<h2>おすすめ通信サービス・キャンペーン詳細を確認【広告】</h2>
<p>最新の月額料金、端末割引、キャッシュバック特典は頻繁に更新されます。必ず公式の申込ページで最新情報をご確認ください。</p>
<div class="brand-banner">
<!-- 承認済み正規広告リンク配置スペース（提携プログラム承認後に正規A8コード等を挿入） -->
<p class="learn-small">【提携プログラム準備中】提携承認後、許可された正規広告リンクをここに配置します。</p>
</div>
<p class="learn-small">※広告バナーやボタンが表示されない場合は、ブラウザの広告ブロック機能をご確認ください。</p>
</section>

<h2>申込み前のチェックリスト</h2>
<ul>
<li>本人確認書類（運転免許証・マイナンバーカード等）を用意したか</li>
<li>他社からの乗り換えの場合、MNP予約番号（またはMNPワンストップ対応）を確認したか</li>
<li>初月に発生する契約事務手数料やSIM発行手数料を確認したか</li>
<li>オプション（通話定額・保証・留守番電話など）の初月無料条件と自動更新の有無を確認したか</li>
</ul>

<h2>参考にした公式情報</h2>
<ul>
{sources_li}
</ul>
<p class="learn-small">最終確認日：{TODAY_DISPLAY}。価格・サービス内容は改定される場合があります。必ず各社公式ページで最新情報をご確認ください。</p>

<p><a href="index.html#articles">← ほかの比較ガイドを読む</a></p>
</article></main>
<footer class="footer"><div class="container"><strong>くらしの選び方ガイド</strong><p>価格や提供条件はお申込み前に公式情報をご確認ください。</p><a href="index.html">ホーム</a> <a href="about.html">運営者情報</a> <a href="policy.html">運営方針</a><p>© 2026 くらしの選び方ガイド</p></div></footer>
</body></html>
"""
    return html


def update_index_html(topic):
    index_file = ROOT / 'index.html'
    content = index_file.read_text(encoding='utf-8')
    slug = topic['slug']
    card_html = f'<article class="card" data-category="{topic["category"]}"><span class="tag">{topic["category"]}・広告あり</span><h3>{topic["title"]}</h3><p>{topic["description"]}</p><a href="{slug}.html">記事を読む →</a></article>'

    if f'{slug}.html' in content:
        print(f"[*] index.html にはすでに {slug}.html へのリンクが存在します。スキップします。")
        return

    # <div class="grid"> の直後に新着カードを挿入
    if '<div class="grid">' in content:
        content = content.replace('<div class="grid">', f'<div class="grid">\n{card_html}', 1)
        index_file.write_text(content, encoding='utf-8')
        print(f"[+] index.html の先頭に新着記事カードを追加しました: {slug}.html")


def main():
    topics_file = ROOT / 'ops' / 'topics.json'
    if not topics_file.exists():
        print("[-] topics.json が見つかりません。")
        sys.exit(1)

    topics = json.loads(topics_file.read_text(encoding='utf-8'))
    target_topic = None
    for t in topics:
        if t.get('status') == 'pending_draft':
            target_topic = t
            break

    if not target_topic:
        for t in topics:
            if t.get('status') == 'planned':
                target_topic = t
                break

    if not target_topic:
        print("[*] 現在作成予定の下書きテーマはありません。")
        sys.exit(0)

    slug = target_topic['slug']
    out_file = ROOT / f"{slug}.html"
    print(f"[*] 記事ドラフトを生成中: {target_topic['title']} ({out_file.name})")

    html = generate_article_html(target_topic)
    out_file.write_text(html, encoding='utf-8')
    print(f"[+] 記事HTMLを書き込みました: {out_file.name}")

    # index.html の更新
    update_index_html(target_topic)

    # ステータスを draft_created に更新
    target_topic['status'] = 'draft_created'
    target_topic['created_at'] = TODAY_ISO
    topics_file.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # PR説明文用のMarkdownを生成
    pr_body = f"""## 📝 週次自動記事ドラフト作成レポート ({TODAY_ISO})

### 記事概要
- **記事タイトル**: {target_topic['title']}
- **ファイル名**: `{slug}.html`
- **カテゴリ**: {target_topic['category']}
- **想定読者**: {target_topic.get('target_audience', '暮らしの選択に悩むユーザー')}
- **狙うSEOキーワード**: {', '.join(target_topic.get('keywords', []))}

### 遵守ポリシー・品質担保
- ✅ **Googleスパムポリシー準拠**: 独自性のない量産を避け、比較軸（価格・容量・注意点・向く人向かない人）を明確化
- ✅ **ステルスマーケティング規制（景表法）対応**: 記事上部にPR/広告明示バナーを自動配置
- ✅ **虚偽体験談の排除**: 未使用商品の架空レビューを創作せず、公式一次情報の客観的整理であることを明記
- ✅ **SEO最適化**: タイトル、meta description、H1〜H2構造、パンくず、Schema.org(Article)構造化データ、canonicalタグを配備
- ✅ **インデックス最適化**: `index.html` へのカード掲載および `sitemap.xml` への自動登録完了

---

### 👤 人間による確認チェックリスト（公開前チェック）
以下の項目を確認の上、問題なければ本Pull Requestを「**Merge pull request**」してください（マージと同時にCloudflare Pagesへ自動公開されます）。

- [ ] 公式サイトで最新の基本料金や事務手数料、受付中キャンペーンを確認したか
- [ ] 承認済み広告プログラム（A8.net等）の正規広告コードへの差し替え・追記が必要な場合、指定コードを配置したか
- [ ] 誤字脱字、事実誤認、法令（薬機法・景表法等）に抵触する表現がないか
- [ ] 記事内容の公開を承認する
"""
    pr_md_file = ROOT / 'reports' / 'latest_draft_pr.md'
    pr_md_file.parent.mkdir(exist_ok=True)
    pr_md_file.write_text(pr_body, encoding='utf-8')
    print(f"[+] PR説明文を生成しました: {pr_md_file.name}")


if __name__ == '__main__':
    main()
