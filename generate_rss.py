#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日本総研 アジア・新興国経済レポート RSSフィード生成スクリプト
"""

import os
import re
import ssl
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone, timedelta
import logging
import urllib3

# SSL警告を抑制（自己署名証明書などの場合）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 設定
URL = "https://www.jri.co.jp/report/theme/asiaemerg/"
OUTPUT_FILE = "jri_asia_rss.xml"
SITE_URL = "https://www.jri.co.jp"
FEED_TITLE = "日本総研 アジア・新興国経済レポート"
FEED_DESCRIPTION = "日本総合研究所が発表するアジア・新興国経済に関するレポートのRSSフィードです"
FEED_LINK = "https://www.jri.co.jp/report/theme/asiaemerg/"
TIMEZONE_OFFSET = 9  # 日本時間 (JST)


def fetch_and_parse():
    """ページを取得してレポート情報を抽出"""
    logger.info(f"Fetching: {URL}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # SSL検証を無効にしてリクエスト（自己署名証明書対応）
        response = requests.get(
            URL, 
            headers=headers, 
            timeout=30,
            verify=False  # SSL証明書の検証をスキップ
        )
        response.raise_for_status()
        
        # 文字コードを自動検出または強制設定
        if response.encoding is None or response.encoding.lower() == 'iso-8859-1':
            response.encoding = 'utf-8'
        else:
            response.encoding = response.apparent_encoding or 'utf-8'
            
        logger.info(f"Response status: {response.status_code}, Encoding: {response.encoding}")
        
    except requests.RequestException as e:
        logger.error(f"Failed to fetch page: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # レポート一覧を抽出 (dl.news-link) - 複数の可能性を試す
    news_dl = soup.find('dl', class_='news-link')
    
    # class_='news-link' が見つからない場合、他のパターンを試す
    if not news_dl:
        logger.warning("'dl.news-link' not found, trying alternative selectors...")
        # classに'news-link'を含むdlを探す
        news_dl = soup.find('dl', class_=re.compile(r'.*news-link.*'))
    
    if not news_dl:
        # div.news-link の可能性も試す
        news_div = soup.find('div', class_=re.compile(r'.*news-link.*'))
        if news_div:
            # div内のdlを探す
            news_dl = news_div.find('dl')
    
    if not news_dl:
        # より一般的なセレクタ: 日付とリンクのパターンを直接探す
        logger.warning("No news-link found, trying direct pattern matching...")
        items = extract_items_directly(soup)
        if items:
            return items
        else:
            logger.error("Could not find any report items in the page")
            # デバッグ用にHTMLの一部を表示
            logger.debug(f"Page title: {soup.title.string if soup.title else 'No title'}")
            return []
    
    items = extract_items_from_dl(news_dl)
    logger.info(f"Found {len(items)} items from dl.news-link")
    return items


def extract_items_from_dl(news_dl):
    """dl要素からアイテムを抽出"""
    items = []
    current_date = None
    
    # dl内の要素を順に処理
    for element in news_dl.children:
        if element.name == 'dt':
            # 日付を取得 (例: "2026年09月01日")
            date_text = element.get_text(strip=True)
            current_date = parse_date(date_text)
            
        elif element.name == 'dd' and current_date:
            # リンクとタイトルを取得
            link_tag = element.find('a')
            if not link_tag:
                continue
                
            # タイトルを抽出 (リンクテキストから)
            title = link_tag.get_text(strip=True)
            
            # リンク先URLを取得
            href = link_tag.get('href', '')
            if not href or href == '#':
                continue
                
            # 相対URLを絶対URLに変換
            if href.startswith('/'):
                full_url = SITE_URL + href
            elif href.startswith('http'):
                full_url = href
            else:
                full_url = SITE_URL + '/' + href.lstrip('/')
            
            # PDFリンクかどうかをチェック
            is_pdf = '.pdf' in href.lower()
            
            # タイトルをクリーンアップ（PDF情報を除去）
            title = clean_title(title, is_pdf)
            
            # 説明文を抽出
            description = ""
            # PDFのサイズ情報を抽出（説明文として使用）
            if is_pdf:
                element_text = element.get_text()
                # PDFサイズ情報を抽出
                size_match = re.search(r'（PDF[：:]\s*([0-9,]+)KB）', element_text)
                if size_match:
                    description = f"PDFファイル ({size_match.group(1)}KB)"
                else:
                    # 別の形式のPDF情報を探す
                    pdf_match = re.search(r'\(PDF[^)]*\)', element_text)
                    if pdf_match:
                        description = f"PDFファイル {pdf_match.group(0)}"
                    else:
                        description = "PDFファイル"
            
            # 重複チェック (同じURLのアイテムはスキップ)
            if any(item['link'] == full_url for item in items):
                continue
            
            items.append({
                'title': title,
                'link': full_url,
                'date': current_date,
                'description': description,
                'is_pdf': is_pdf,
                'guid': full_url
            })
            
            logger.debug(f"Added: {title[:50]}...")
    
    return items


def clean_title(title, is_pdf=False):
    """タイトルからPDF情報などの余計な部分を削除"""
    # PDFサイズ情報を除去 (例: "（PDF：979KB）" や "(PDF: 979KB)")
    title = re.sub(r'\s*[（(]PDF[：:]\s*[0-9,]+\s*KB[）)]\s*$', '', title)
    title = re.sub(r'\s*[（(]PDF[^）)]*[）)]\s*$', '', title)
    
    # 先頭の [PDF] を除去（もしあれば）
    title = re.sub(r'^\[PDF\]\s*', '', title)
    
    # 余分な空白を削除
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title


def extract_items_directly(soup):
    """直接パターンマッチングでアイテムを抽出（フォールバック）"""
    items = []
    
    # 日付とリンクのペアを探す
    # dtとddのペアを直接検索
    dt_elements = soup.find_all('dt')
    
    for dt in dt_elements:
        # 日付形式かチェック
        date_text = dt.get_text(strip=True)
        if not re.search(r'\d{4}年\d{1,2}月\d{1,2}日', date_text):
            continue
            
        current_date = parse_date(date_text)
        if not current_date:
            continue
            
        # 次のdd要素を探す
        next_dd = dt.find_next_sibling('dd')
        if not next_dd:
            continue
            
        link_tag = next_dd.find('a')
        if not link_tag:
            continue
            
        title = link_tag.get_text(strip=True)
        href = link_tag.get('href', '')
        
        if not href or href == '#':
            continue
            
        # URLを絶対パスに変換
        if href.startswith('/'):
            full_url = SITE_URL + href
        elif href.startswith('http'):
            full_url = href
        else:
            full_url = SITE_URL + '/' + href.lstrip('/')
        
        # PDFチェック
        is_pdf = '.pdf' in href.lower()
        
        # タイトルをクリーンアップ
        title = clean_title(title, is_pdf)
        
        # 重複チェック
        if any(item['link'] == full_url for item in items):
            continue
            
        items.append({
            'title': title,
            'link': full_url,
            'date': current_date,
            'description': "PDFファイル" if is_pdf else "",
            'is_pdf': is_pdf,
            'guid': full_url
        })
    
    logger.info(f"Found {len(items)} items via direct pattern matching")
    return items


def parse_date(date_text):
    """日付文字列をdatetimeオブジェクトに変換"""
    # "2026年09月01日" 形式に対応
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        # JSTでdatetimeを作成 (時刻は00:00)
        return datetime(year, month, day, tzinfo=timezone(timedelta(hours=TIMEZONE_OFFSET)))
    return None


def generate_rss(items):
    """RSSフィードを生成"""
    if not items:
        logger.warning("No items to generate RSS")
        return False
    
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.description(FEED_DESCRIPTION)
    fg.link(href=FEED_LINK, rel='alternate')
    fg.language('ja')
    
    # 現在時刻を最終更新日時に設定
    now = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    fg.lastBuildDate(now)
    fg.pubDate(now)
    
    # アイテムを日付の降順（新しい順）にソート
    sorted_items = sorted(
        [item for item in items if item['date'] is not None],
        key=lambda x: x['date'],
        reverse=True
    )
    
    # 最新50件に制限（オプション）
    if len(sorted_items) > 50:
        sorted_items = sorted_items[:50]
        logger.info(f"Limited to 50 items")
    
    for item in sorted_items:
        fe = fg.add_entry()
        fe.title(item['title'])
        fe.link(href=item['link'], rel='alternate')
        fe.guid(item['guid'], permalink=True)
        fe.pubDate(item['date'])
        
        # 説明文を設定
        if item['description']:
            description = item['description']
        else:
            description = f"{item['title']} - 日本総研 アジア・新興国経済レポート"
        fe.description(description)
    
    # RSSファイルに保存
    fg.rss_file(OUTPUT_FILE, pretty=True)
    logger.info(f"RSS feed generated: {OUTPUT_FILE} ({len(sorted_items)} items)")
    return True


def main():
    """メイン処理"""
    logger.info("Starting RSS feed generation...")
    
    try:
        items = fetch_and_parse()
        if items:
            success = generate_rss(items)
            if success:
                logger.info("RSS generation completed successfully")
            else:
                logger.error("RSS generation failed")
                exit(1)
        else:
            logger.warning("No items found, skipping RSS generation")
            exit(1)
    except Exception as e:
        logger.error(f"Error during RSS generation: {e}")
        import traceback
        logger.error(traceback.format_exc())
        exit(1)


if __name__ == "__main__":
    main()
