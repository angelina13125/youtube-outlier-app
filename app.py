# app.py - Optimized YouTube Outlier Finder (Saved Channels + Research)
import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import isodate
import random
import io
from urllib.parse import urlparse

# -----------------------
# CONFIG
# -----------------------
API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE" # <-- set in Streamlit secrets
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

SEARCH_RESULTS_PER_KEYWORD = 10
CHANNEL_LOOKBACK_VIDEOS_DEFAULT = 50
VIDEOS_BATCH_SIZE = 50
MAX_CHANNELS_PER_FETCH = 10

# -----------------------
# SESSION CACHES
# -----------------------
if "channel_cache" not in st.session_state:
    st.session_state.channel_cache = {}

if "video_cache" not in st.session_state:
    st.session_state.video_cache = {}

if "playlist_cache" not in st.session_state:
    st.session_state.playlist_cache = {}

# -----------------------
# HELPERS
# -----------------------
def parse_channel_id(value: str):
    value = value.strip()
    if value == "":
        return None
    try:
        u = urlparse(value)
        if u.netloc.endswith("youtube.com"):
            path = u.path.strip("/").split("/")
            if len(path) >= 2 and path[0] == "channel":
                return path[1]
        return value
    except Exception:
        return value

def safe_api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs).execute()
    except Exception as e:
        st.error(f"YouTube API error: {e}")
        return None

def get_channel_info(channel_id):
    if not channel_id:
        return None
    if channel_id in st.session_state.channel_cache:
        return st.session_state.channel_cache[channel_id]
    res = safe_api_call(YOUTUBE.channels().list, part="statistics,snippet,contentDetails", id=channel_id)
    if not res or 'items' not in res or not res['items']:
        st.session_state.channel_cache[channel_id] = None
        return None
    item = res['items'][0]
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    info = {
        "channel_id": channel_id,
        "title": snippet.get("title", "Unknown"),
        "subs": int(stats.get("subscriberCount") or 0),
        "total_views": int(stats.get("viewCount") or 0),
        "video_count": int(stats.get("videoCount") or 0),
        "created_at": snippet.get("publishedAt"),
        "profile_pic": snippet.get("thumbnails", {}).get("default", {}).get("url"),
        "uploads_playlist": content.get("relatedPlaylists", {}).get("uploads")
    }
    st.session_state.channel_cache[channel_id] = info
    return info

def chunk_list(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

def fetch_videos_details(video_ids):
    to_fetch = [vid for vid in video_ids if vid not in st.session_state.video_cache]
    for chunk in chunk_list(to_fetch, VIDEOS_BATCH_SIZE):
        resp = safe_api_call(YOUTUBE.videos().list, part="snippet,statistics,contentDetails",
                             id=",".join(chunk), maxResults=VIDEOS_BATCH_SIZE)
        if not resp:
            continue
        for item in resp.get("items", []):
            vid = item.get("id")
            sn = item.get("snippet", {})
            stt = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            try:
                duration_s = int(isodate.parse_duration(cd.get("duration", "PT0S")).total_seconds())
            except Exception:
                duration_s = None
            st.session_state.video_cache[vid] = {
                "video_id": vid,
                "title": sn.get("title"),
                "thumbnail": sn.get("thumbnails", {}).get("medium", {}).get("url"),
                "publishedAt": sn.get("publishedAt"),
                "views": int(stt.get("viewCount") or 0),
                "likes": int(stt.get("likeCount") or 0) if "likeCount" in stt else None,
                "comments": int(stt.get("commentCount") or 0) if "commentCount" in stt else None,
                "duration_s": duration_s,
                "channelId": sn.get("channelId"),
                "channelTitle": sn.get("channelTitle")
            }
    return {vid: st.session_state.video_cache.get(vid) for vid in video_ids if st.session_state.video_cache.get(vid)}

def get_uploads_video_ids_from_channel(channel_id, max_videos=100):
    channel_info = get_channel_info(channel_id)
    if not channel_info:
        return []
    playlist_id = channel_info.get("uploads_playlist")
    if not playlist_id:
        return []
    if playlist_id in st.session_state.playlist_cache:
        cached = st.session_state.playlist_cache[playlist_id]
        if len(cached) >= max_videos:
            return cached[:max_videos]
    video_ids = []
    req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=50)
    while req and len(video_ids) < max_videos:
        try:
            resp = req.execute()
        except Exception as e:
            st.error(f"Playlist fetch error: {e}")
            break
        for it in resp.get("items", []):
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
            if len(video_ids) >= max_videos:
                break
        req = YOUTUBE.playlistItems().list_next(req, resp)
    st.session_state.playlist_cache[playlist_id] = video_ids
    return video_ids[:max_videos]

def iso_to_dt(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None

def render_video_card(col, row):
    thumb = row.get("thumbnail")
    title = row.get("title")
    url = row.get("video_url") or f"https://www.youtube.com/watch?v={row.get('video_id')}"
    channel = row.get("channel_title")
    subs = row.get("subs")
    views = row.get("views")
    outlier = row.get("outlier")
    published = row.get("publishedAt")
    duration_s = row.get("duration_s")

    if thumb:
        col.image(thumb, use_column_width=True)
    col.markdown(f"### [{title}]({url})")
    if channel:
        ch_line = channel
        if subs is not None:
            ch_line += f" — {int(subs):,} subs"
        col.write(ch_line)
    stats_line = ""
    if views is not None:
        stats_line += f"Views: {int(views):,}  "
    if outlier is not None:
        stats_line += f" |  **Outlier: {outlier}x**"
    if stats_line:
        col.write(stats_line)
    if published:
        dt = iso_to_dt(published)
        if dt:
            col.write(f"Published: {dt.date()}")
    if duration_s:
        mins = duration_s // 60
        col.write(f"Duration: {mins}m {duration_s%60}s")

# -----------------------
# APP UI
# -----------------------
st.set_page_config(page_title="YouTube Outlier Finder", layout="wide")
st.title("🎯 YouTube Outlier Finder")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# -----------------------
# SAVED CHANNELS TAB
# -----------------------
with tab1:
    st.header("Saved Channels Tool")
    st.caption("Paste channel IDs or URLs (comma-separated). Example: https://www.youtube.com/channel/UC_xxx")
    channel_input = st.text_area("Channels (IDs or URLs)", value="", height=80)
    max_results = st.slider("Videos per channel to fetch (recent)", 5, 100, 25)
    lookback_min, lookback_max = st.slider("Channel average lookback (videos)", 5, 100, (5, 50))
    min_views = st.number_input("Min views (filter)", value=0, step=1000)
    view_subs_ratio_min = st.number_input("Min views:subs ratio (filter)", value=0.0, step=0.1)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"])
    sort_by = st.selectbox("Sort by", ["Random", "Views", "Outlier Score", "Published"])

    if st.button("Fetch Saved Channel Videos"):
        ids = [parse_channel_id(x) for x in channel_input.split(",") if x.strip()]
        ids = ids[:MAX_CHANNELS_PER_FETCH]
        all_video_rows = []
        channel_table = []
        for cid in ids:
            ch = get_channel_info(cid)
            if not ch:
                st.warning(f"No data for channel: {cid}")
                continue
            channel_table.append({
                "Channel": ch["title"],
                "Subscribers": ch["subs"],
                "Total Views": ch["total_views"],
                "Video Count": ch["video_count"],
                "Created": ch["created_at"]
            })
            vids = get_uploads_video_ids_from_channel(cid, max_videos=max_results)
            fetch_videos_details(vids)

            # dynamic lookback sample
            sample_count = random.randint(lookback_min, lookback_max)
            look_ids = vids[:sample_count] if len(vids) >= sample_count else vids
            fetch_videos_details(look_ids)
            counts = [st.session_state.video_cache[v].get("views", 0) for v in look_ids if v in st.session_state.video_cache]
            avg_views = sum(counts)/len(counts) if counts else 1  # fallback 1 to avoid div zero

            for vid in vids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                ds = d.get("duration_s")
                typ = "Shorts" if ds is not None and ds < 60 else "Long-form"
                if content_type == "Shorts" and typ != "Shorts":
                    continue
                if content_type == "Long-form" and typ != "Long-form":
                    continue
                views = d.get("views", 0)
                if views < min_views:
                    continue
                subs = ch.get("subs", 0)
                ratio = (views / subs) if subs else float('inf')
                if ratio < view_subs_ratio_min:
                    continue
                outlier = round(views / avg_views, 2)
                all_video_rows.append({
                    "video_id": vid,
                    "title": d.get("title"),
                    "thumbnail": d.get("thumbnail"),
                    "publishedAt": d.get("publishedAt"),
                    "video_url": f"https://www.youtube.com/watch?v={vid}",
                    "views": views,
                    "duration_s": ds,
                    "type": typ,
                    "channel_title": ch["title"],
                    "subs": ch["subs"],
                    "outlier": outlier
                })

        if channel_table:
            st.subheader("Channels (summary)")
            st.dataframe(pd.DataFrame(channel_table))
        if not all_video_rows:
            st.warning("No videos matched your filters.")
        else:
            df = pd.DataFrame(all_video_rows)
            if sort_by == "Views":
                df = df.sort_values(by="views", ascending=False)
            elif sort_by == "Outlier Score":
                df = df.sort_values(by="outlier", ascending=False)
            elif sort_by == "Published":
                df = df.sort_values(by="publishedAt", ascending=False)
            elif sort_by == "Random":
                df = df.sample(frac=1).reset_index(drop=True)

            st.subheader(f"Videos ({len(df)})")
            for i in range(0, len(df), 4):
                cols = st.columns(4)
                for j, col in enumerate(cols):
                    idx = i + j
                    if idx < len(df):
                        render_video_card(col, df.iloc[idx])

            output = io.BytesIO()
            df.to_excel(output, index=False)
            st.download_button(
                "Download saved channels results (.xlsx)",
                data=output.getvalue(),
                file_name="saved_channels_videos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# -----------------------
# RESEARCH TAB
# -----------------------
# (Keep your Research tab mostly unchanged — it already fetches candidate videos dynamically)
# You may want to copy the same "lookback" improvements if needed.

st.markdown("---")
st.caption("Built with YouTube Data API v3 — keeps results cached in-session to reduce API quota usage.")




