import os, re, json, textwrap
import requests
from bs4 import BeautifulSoup

LIST_URL = "https://lod.nexon.com/news/notice"
BASE = "https://lod.nexon.com"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
STATE_FILE = "state.json"

UA = {"User-Agent": "Mozilla/5.0 (compatible; LODNoticeBot/1.0)"}

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_id": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def soup_from(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def get_latest_post_id_and_url():
    soup = soup_from(LIST_URL)
    # 목록에서 /News/notice/{id} 형태 링크가 실제로 존재 :contentReference[oaicite:6]{index=6}
    a = soup.select_one('a[href^="/News/notice/"], a[href^="/news/notice/"]')
    if not a:
        raise RuntimeError("목록에서 공지 링크를 못 찾음(페이지 구조 변경 가능).")
    href = a.get("href", "")
    m = re.search(r"/[Nn]ews/notice/(\d+)", href)
    if not m:
        raise RuntimeError(f"공지 ID 파싱 실패: {href}")
    post_id = m.group(1)
    url = href if href.startswith("http") else BASE + href
    return post_id, url

def extract_main_text_and_images(detail_url: str):
    soup = soup_from(detail_url)

    # 스크립트/스타일 제거
    for t in soup(["script", "style", "noscript"]):
        t.decompose()

    # 제목 후보: h1/h2/h3 중 제일 그럴듯한 거
    title = None
    for tag in ["h1", "h2", "h3"]:
        h = soup.find(tag)
        if h and h.get_text(strip=True):
            title = h.get_text(" ", strip=True)
            break
    if not title:
        title = soup.title.get_text(" ", strip=True) if soup.title else "어둠의전설 공지"

    # 본문 후보: div/section/main 중 “텍스트가 가장 긴” 블록을 본문으로 간주 (구조 변경에 비교적 강함)
    candidates = soup.find_all(["main", "section", "div"], limit=5000)
    best = None
    best_len = 0
    for c in candidates:
        txt = c.get_text("\n", strip=True)
        # 너무 짧은 건 제외
        if len(txt) > best_len and len(txt) >= 200:
            best = c
            best_len = len(txt)

    if not best:
        best = soup.body or soup

    body_text = best.get_text("\n", strip=True)

    # 이미지 링크 추출(본문 블록 안의 img)
    imgs = []
    for img in best.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = BASE + src
        imgs.append(src)
    # 중복 제거
    imgs = list(dict.fromkeys(imgs))

    return title, body_text, imgs

def post_to_discord(messages):
    # 디스코드 content 2000자 제한 때문에 쪼갬 :contentReference[oaicite:7]{index=7}
    for msg in messages:
        r = requests.post(WEBHOOK, json={"content": msg}, timeout=20)
        r.raise_for_status()

def chunk_text(text: str, chunk_size: int = 1800):
    # 줄바꿈이 없거나 한 줄이 너무 길어도 무조건 글자수로 잘라서 2000자 제한을 피함
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    i = 0
    n = len(text)
    while i < n:
        chunks.append(text[i:i+chunk_size])
        i += chunk_size
    return chunks

def build_messages(title, detail_url, body_text, imgs):
    header = f"📢 **{title}**\n<{detail_url}>"
    messages = [header]

    # 본문은 여러 메시지로 분할
    for part in chunk_text(body_text, 1800):
        messages.append(part)

    # 이미지가 있으면 마지막에 링크로 추가
    if imgs:
        img_block = "**이미지**\n" + "\n".join(imgs)
        for part in chunk_text(img_block, 1800):
            messages.append(part)

    return messages

def main():
    state = load_state()
    post_id, detail_url = get_latest_post_id_and_url()

    if state["last_id"] == post_id:
        return

    title, body_text, imgs = extract_main_text_and_images(detail_url)
    messages = build_messages(title, detail_url, body_text, imgs)

    # 첫 실행은 과거 공지로 도배 방지: 전송 없이 last_id만 저장
    post_to_discord(messages)

    state["last_id"] = post_id
    save_state(state)

if __name__ == "__main__":
    main()
