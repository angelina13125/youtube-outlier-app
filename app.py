# app.py - Final optimized YouTube Outlier Finder (Saved Channels + Research)
import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import isodate
import random
import io
import math
from urllib.parse import urlparse, parse_qs

# -----------------------
# CONFIG
# -----------------------
API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"  # <-- REPLACE with your key or use Streamlit Secrets
YOUTUBE = build("youtube", "v3", developerKey=API_KEY)

# Tune these to balance quota vs results
SEARCH_RESULTS_PER_KEYWORD = 10  # how many search results to request per keyword
CHANNEL_LOOKBACK_VIDEOS = 50     # how many recent uploads to use when computing channel average
VIDEOS_BATCH_SIZE = 50           # batch size for videos().list (max 50)
MAX_CHANNELS_PER_FETCH = 10      # safety guard

# -----------------------
# SESSION CACHES
# -----------------------
if "channel_cache" not in st.session_state:
    st.session_state.channel_cache = {}   # channel_id -> channel_info dict

if "video_cache" not in st.session_state:
    st.session_state.video_cache = {}     # video_id -> video_details dict

if "playlist_cache" not in st.session_state:
    st.session_state.playlist_cache = {}  # channel_id -> uploads playlist id

# -----------------------
# HELPERS
# -----------------------
def parse_channel_id(value: str):
    """Try to extract a channel ID from a pasted URL or return the string as-is."""
    value = value.strip()
    if value == "":
        return None
    # common formats:
    # https://www.youtube.com/channel/UCxxxx
    # https://www.youtube.com/c/CustomName  (can't get ID from this without extra calls)
    # https://www.youtube.com/watch?v=VIDEOID
    try:
        u = urlparse(value)
        if u.netloc.endswith("youtube.com"):
            path = u.path.strip("/").split("/")
            if len(path) >= 2 and path[0] == "channel":
                return path[1]
            # if it's a watch URL, extract channel via video? skip here
        # fallback: assume user pasted an ID directly
        return value
    except Exception:
        return value

def safe_api_call(fn, *args, **kwargs):
    """Call YouTube API method and catch HttpError to show a friendly message."""
    try:
        return fn(*args, **kwargs).execute()
    except Exception as e:
        st.error(f"YouTube API error: {e}")
        return None

def get_channel_info(channel_id):
    """Get channel stats and store in cache. Returns dict or None."""
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
    """Fetch video details (snippet, statistics, contentDetails) in batches with caching."""
    to_fetch = [vid for vid in video_ids if vid not in st.session_state.video_cache]
    for chunk in chunk_list(to_fetch, VIDEOS_BATCH_SIZE):
        resp = safe_api_call(YOUTUBE.videos().list, part="snippet,statistics,contentDetails", id=",".join(chunk), maxResults=VIDEOS_BATCH_SIZE)
        if not resp:
            continue
        for item in resp.get("items", []):
            vid = item.get("id")
            sn = item.get("snippet", {})
            stt = item.get("statistics", {})
            cd = item.get("contentDetails", {})
            # parse duration to seconds
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
    # return details for requested ids (from cache)
    return {vid: st.session_state.video_cache.get(vid) for vid in video_ids if st.session_state.video_cache.get(vid)}

def get_uploads_video_ids_from_channel(channel_id, max_videos=100):
    """Return recent upload video IDs from uploads playlist, using cache."""
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
    # fetch playlist items
    video_ids = []
    req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=50)
    while req and len(video_ids) < max_videos:
        resp = safe_api_call(req.execute if False else req)  # weird to support safe_api_call, simpler below
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

# -----------------------
# UI Utility
# -----------------------
def render_video_card(col, row):
    """Render single video row dict in a column (col is a streamlit column), row is a pandas Series or dict"""
    thumb = row.get("thumbnail") or row.get("Thumbnail")
    title = row.get("title") or row.get("Title")
    url = row.get("video_url") or row.get("Video URL") or f"https://www.youtube.com/watch?v={row.get('video_id')}"
    channel = row.get("channel_title") or row.get("Channel") or row.get("channelTitle")
    subs = row.get("subs") or row.get("Subscribers") or row.get("SubscribersCount") or row.get("Subs")
    views = row.get("views") or row.get("Views")
    outlier = row.get("outlier") or row.get("Outlier Score") or row.get("Outlier")
    published = row.get("publishedAt") or row.get("Published")
    duration_s = row.get("duration_s") or row.get("DurationSeconds") or row.get("Duration")
    # thumbnail
    if thumb:
        col.image(thumb, use_column_width=True)
    # title clickable
    col.markdown(f"### [{title}]({url})")
    # channel + subs
    if channel:
        ch_line = channel
        if subs is not None:
            ch_line += f" — {int(subs):,} subs"
        col.write(ch_line)
    # stats
    stats_line = ""
    if views is not None:
        stats_line += f"Views: {int(views):,}  "
    if outlier is not None:
        stats_line += f" |  **Outlier: {outlier}x**"
    if stats_line:
        col.write(stats_line)
    # publish
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
st.title("🎯 YouTube Outlier Finder — Saved Channels & Research (Quota-friendly)")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# -----------------------
# SAVED CHANNELS TAB
# -----------------------
with tab1:
    st.header("Saved Channels Tool")
    st.caption("Paste channel IDs or channel URLs (comma-separated). Example channel URL: https://www.youtube.com/channel/UC_xxx")
    channel_input = st.text_area("Channels (IDs or URLs)", value="", height=80)
    max_results = st.slider("Videos per channel to fetch (recent)", 5, 100, 25)
    lookback = st.slider("Channel average lookback (videos)", 5, 100, CHANNEL_LOOKBACK_VIDEOS)
    min_views = st.number_input("Min views (filter)", value=0, step=1000)
    view_subs_ratio_min = st.number_input("Min views:subs ratio (filter)", value=0.0, step=0.1)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"])
    sort_by = st.selectbox("Sort by", ["Random", "Views", "Outlier Score", "Published"])
    if st.button("Fetch Saved Channel Videos"):
        ids = [parse_channel_id(x) for x in channel_input.split(",") if x.strip()]
        ids = ids[:MAX_CHANNELS_PER_FETCH]  # safety
        all_video_rows = []
        channel_table = []
        for cid in ids:
            info = get_channel_info = get_channel_info if False else get_channel_info  # noop to avoid linter warnings
            ch = get_channel_info(cid) if cid else None
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
            # get uploads
            vids = get_uploads_video_ids_from_channel(cid, max_videos=max_results)
            # fetch details in batches
            details_map = fetch_videos_details(vids)
            # compute channel avg from lookback
            # fallback compute from available cached details
            look_ids = vids[:lookback]
            look_map = fetch_videos_details(look_ids)
            avg_views = 0
            counts = [d.get("views", 0) for d in look_map.values()]
            if counts:
                avg_views = sum(counts) / len(counts)
            else:
                # fallback to channel total / video_count
                avg_views = ch["total_views"] / max(ch["video_count"], 1)
            for vid in vids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                # duration -> short detection
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
                outlier = round(views / avg_views, 2) if avg_views else 0
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

            # excel export
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
with tab2:
    st.header("Research (Outlier Finder)")
    st.caption("Use framing keywords (e.g., 'I tried', 'My story') or your own terms.")
    keywords_input = st.text_area("Keywords (comma separated)", value="I tried, My story, Top 10", height=80)
    num_results = st.slider("Number of random results to return", 5, 200, 50)
    # Filters
    min_views = st.number_input("Min views", value=100_000, step=10_000)
    min_subs = st.number_input("Min channel subscribers", value=0, step=1000)
    min_outlier = st.number_input("Min outlier multiplier (views ÷ channel avg)", value=5.0, step=0.1)
    min_views_subs_ratio = st.number_input("Min views:subs ratio", value=0.0, step=0.1)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"])
    include_keywords = st.text_input("Include keywords (optional, comma separated)")
    exclude_keywords = st.text_input("Exclude keywords (optional, comma separated)")
    include_channels = st.text_input("Include channels (optional, comma separated - channel IDs)")
    exclude_channels = st.text_input("Exclude channels (optional, comma separated - channel IDs)")

    # date presets + custom
    preset = st.selectbox("Date range preset", ["All Time", "Last 30 Days", "Last 90 Days", "Last 180 Days", "Last 365 Days", "Custom"])
    date_range = None
    if preset == "Custom":
        start_date = st.date_input("Start date", datetime.utcnow() - timedelta(days=90))
        end_date = st.date_input("End date", datetime.utcnow())
        date_range = (datetime.combine(start_date, datetime.min.time()).isoformat() + "Z",
                      datetime.combine(end_date, datetime.max.time()).isoformat() + "Z")
    elif preset != "All Time":
        days = int(preset.split()[1])
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        date_range = (start.isoformat("T") + "Z", end.isoformat("T") + "Z")

    if st.button("Random"):
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
        include_ks = [k.strip() for k in include_keywords.split(",") if k.strip()]
        exclude_ks = [k.strip() for k in exclude_keywords.split(",") if k.strip()]
        include_chs = [parse_channel_id(x) for x in include_channels.split(",") if x.strip()]
        exclude_chs = [parse_channel_id(x) for x in exclude_channels.split(",") if x.strip()]

        # gather candidate video ids (search per keyword)
        candidate_ids = []
        for kw in keywords:
            try:
                resp = safe_api_call(YOUTUBE.search().list, part="id,snippet", q=kw, type="video", maxResults=SEARCH_RESULTS_PER_KEYWORD, order="viewCount", publishedAfter=(date_range[0] if date_range else None), publishedBefore=(date_range[1] if date_range else None))
                if not resp:
                    continue
                items = resp.get("items", [])
                for it in items:
                    vid = it.get("id", {}).get("videoId")
                    if vid:
                        candidate_ids.append(vid)
            except Exception as e:
                st.warning(f"Search error for '{kw}': {e}")

        # dedupe
        candidate_ids = list(dict.fromkeys(candidate_ids))
        if not candidate_ids:
            st.warning("No candidate videos found for those keywords / date range.")
        else:
            # fetch details in batches & compute outlier and channel filters
            fetch_videos_details(candidate_ids)
            final_rows = []
            # To compute channel averages efficiently, gather channel -> sample of video IDs
            # We'll compute channel averages from cached video data where available (lookback)
            channel_to_look_ids = {}
            for vid in candidate_ids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                ch = d.get("channelId")
                channel_to_look_ids.setdefault(ch, [])
                # add recent vids we have in cache for that channel
                channel_to_look_ids[ch].append(vid)

            # compute each channel avg using cached details or via channel total
            channel_avg_map = {}
            for ch, vids in channel_to_look_ids.items():
                # try to use up to CHANNEL_LOOKBACK_VIDEOS cached vids
                vids_sample = vids[:CHANNEL_LOOKBACK_VIDEOS]
                fetch_videos_details(vids_sample)
                vals = [st.session_state.video_cache[v].get("views", 0) for v in vids_sample if v in st.session_state.video_cache]
                if vals:
                    channel_avg_map[ch] = sum(vals)/len(vals)
                else:
                    chinfo = get_channel_info = get_channel_info if False else get_channel_info  # noop
                    chinfo = get_channel_info(ch)
                    if chinfo:
                        channel_avg_map[ch] = chinfo['total_views'] / max(chinfo['video_count'], 1)
                    else:
                        channel_avg_map[ch] = 0

            # Evaluate candidates
            for vid in candidate_ids:
                d = st.session_state.video_cache.get(vid)
                if not d:
                    continue
                title = d.get("title","")
                ch = d.get("channelId")
                chinfo = get_channel_info(ch)
                ch_subs = chinfo['subs'] if chinfo else 0
                if include_chs and ch not in include_chs:
                    continue
                if exclude_chs and ch in exclude_chs:
                    continue
                if include_ks and not any(kw.lower() in title.lower() for kw in include_ks):
                    continue
                if exclude_ks and any(kw.lower() in title.lower() for kw in exclude_ks):
                    continue
                views = d.get("views",0)
                if views < min_views:
                    continue
                if ch_subs < min_subs:
                    continue
                channel_avg = channel_avg_map.get(ch, 0)
                outlier = round(views / channel_avg, 2) if channel_avg else 0
                if outlier < min_outlier:
                    continue
                ratio = (views / ch_subs) if ch_subs else float('inf')
                if ratio < min_views_subs_ratio:
                    continue
                ds = d.get("duration_s")
                typ = "Shorts" if ds is not None and ds < 60 else "Long-form"
                if content_type == "Shorts" and typ != "Shorts":
                    continue
                if content_type == "Long-form" and typ != "Long-form":
                    continue
                final_rows.append({
                    "video_id": vid,
                    "title": title,
                    "thumbnail": d.get("thumbnail"),
                    "publishedAt": d.get("publishedAt"),
                    "video_url": f"https://www.youtube.com/watch?v={vid}",
                    "views": views,
                    "outlier": outlier,
                    "channel_title": d.get("channelTitle"),
                    "subs": ch_subs,
                    "type": typ,
                    "duration_s": ds
                })

            if not final_rows:
                st.warning("No videos matched filters after evaluation.")
            else:
                # random sample up to num_results
                final_sample = random.sample(final_rows, min(num_results, len(final_rows)))
                df = pd.DataFrame(final_sample)
                st.subheader(f"Outlier results ({len(df)})")
                for i in range(0, len(df), 4):
                    cols = st.columns(4)
                    for j, col in enumerate(cols):
                        idx = i + j
                        if idx < len(df):
                            row = df.iloc[idx].to_dict()
                            # render card (with green outlier)
                            if row.get("thumbnail"):
                                col.image(row["thumbnail"], use_column_width=True)
                            col.markdown(f"### [{row['title']}]({row['video_url']})")
                            col.write(f"{row['channel_title']} — {int(row['subs']):,} subs")
                            col.markdown(f"<span style='color:green;font-weight:700'>Outlier: {row['outlier']}x</span>", unsafe_allow_html=True)
                            col.write(f"Views: {int(row['views']):,}")
                            dt = iso_to_dt(row['publishedAt'])
                            if dt:
                                col.write(f"Published: {dt.date()}")
                            if row.get("duration_s"):
                                mins = row['duration_s']//60
                                col.write(f"Duration: {mins}m {row['duration_s']%60}s")

                # export excel
                output = io.BytesIO()
                df.to_excel(output, index=False)
                st.download_button(
                    "Download research results (.xlsx)",
                    data=output.getvalue(),
                    file_name="research_outliers.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

st.markdown("---")
st.caption("Built with YouTube Data API v3 — keeps results cached in-session to reduce API quota usage.")


