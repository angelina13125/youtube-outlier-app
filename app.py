import streamlit as st
import pandas as pd
import random
import io
import re
from datetime import datetime
from googleapiclient.discovery import build
import openpyxl  # needed for Excel export

# --------------------------
# API Key Setup
# --------------------------
YOUTUBE_API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"

youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# --------------------------
# Helpers
# --------------------------
def normalize_channel_url(url):
    url = url.strip()
    handle = url.replace("https://", "").replace("http://", "")
    handle = handle.replace("www.youtube.com/", "").replace("youtube.com/", "")
    handle = handle.replace("@", "")
    return handle

def parse_duration(duration_str):
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    total_minutes = int(hours or 0) * 60 + int(minutes or 0) + int(seconds or 0) / 60
    return total_minutes

def get_channel_videos(channel_handle, max_results=10, long_form=True):
    """Fetch videos for a channel (simplified)."""
    videos = []
    try:
        # get uploads playlist
        search_res = youtube.search().list(
            part="snippet",
            channelId=None,
            q=None,
            type="video",
            maxResults=max_results,
            order="date"
        ).execute()
        for item in search_res.get("items", []):
            vid = item["id"]["videoId"]
            snip = item["snippet"]
            stats = youtube.videos().list(part="statistics,contentDetails", id=vid).execute()
            if not stats["items"]:
                continue
            s = stats["items"][0]
            duration = parse_duration(s["contentDetails"]["duration"])
            if long_form and duration < 8:
                continue
            videos.append({
                "Title": snip["title"],
                "Views": int(s["statistics"].get("viewCount", 0)),
                "Published": snip["publishedAt"][:10],
                "Thumbnail": snip["thumbnails"]["medium"]["url"],
                "Video URL": f"https://www.youtube.com/watch?v={vid}",
                "Channel": snip["channelTitle"],
                "Duration": duration
            })
    except Exception as e:
        st.warning(f"Error fetching channel {channel_handle}: {e}")
    return videos

def fetch_random_videos(keywords, num_results=20, long_form=True, min_outlier=1.0):
    """Fetch random videos by keyword (simplified)."""
    all_videos = []
    for kw in keywords:
        res = youtube.search().list(part="snippet", q=kw, type="video", maxResults=50, order="relevance").execute()
        for item in res.get("items", []):
            vid = item["id"]["videoId"]
            snip = item["snippet"]
            stats = youtube.videos().list(part="statistics,contentDetails", id=vid).execute()
            if not stats["items"]:
                continue
            s = stats["items"][0]
            duration = parse_duration(s["contentDetails"]["duration"])
            if long_form and duration < 8:
                continue
            views = int(s["statistics"].get("viewCount", 0))
            all_videos.append({
                "Title": snip["title"],
                "Views": views,
                "Published": snip["publishedAt"][:10],
                "Thumbnail": snip["thumbnails"]["medium"]["url"],
                "Video URL": f"https://www.youtube.com/watch?v={vid}",
                "Keyword": kw,
                "Duration": duration
            })
    random.shuffle(all_videos)
    if all_videos:
        avg_views = sum(v["Views"] for v in all_videos)/len(all_videos)
        for v in all_videos:
            v["Outlier Score"] = round(v["Views"]/avg_views,2)
        all_videos = [v for v in all_videos if v["Outlier Score"] >= min_outlier]
    return all_videos[:num_results]

# --------------------------
# Streamlit Layout
# --------------------------
st.set_page_config(page_title="YouTube Outlier App", layout="wide")
st.title("📊 YouTube Outlier Finder")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# --------------------------
# TAB 1: Saved Channels
# --------------------------
with tab1:
    st.header("Saved Channels")
    channel_input = st.text_area("Enter channel URLs (comma or newline separated)")
    num_videos = st.slider("Videos per channel", 5, 50, 10)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"])
    sort_by = st.selectbox("Sort by", ["Random", "Views", "Outlier"])

    if st.button("Fetch Videos from Channels"):
        channels = re.split(r"[\n,]+", channel_input)
        all_videos = []
        for url in channels:
            handle = normalize_channel_url(url)
            long_form = True if content_type=="Long-form" else False
            vids = get_channel_videos(handle, num_videos, long_form=long_form)
            if not vids:
                st.warning(f"No data for channel: {url}")
            else:
                avg_views = sum(v["Views"] for v in vids)/len(vids)
                for v in vids:
                    v["Outlier Score"] = round(v["Views"]/avg_views,2)
                all_videos.extend(vids)

        if all_videos:
            df = pd.DataFrame(all_videos)
            if sort_by=="Views":
                df = df.sort_values("Views", ascending=False)
            elif sort_by=="Outlier":
                df = df.sort_values("Outlier Score", ascending=False)
            else:
                df = df.sample(frac=1)
            st.dataframe(df[["Title","Channel","Views","Outlier Score","Published"]], use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            st.download_button("Export Excel", data=output.getvalue(),
                               file_name="channel_videos.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("No videos found.")

# --------------------------
# TAB 2: Research
# --------------------------
with tab2:
    st.header("Keyword Research")
    keyword_input = st.text_area("Enter keywords (comma separated)")
    num_results = st.slider("Number of random videos", 5, 50, 20)
    content_type = st.selectbox("Content type", ["All", "Long-form", "Shorts"], key="r_content_type")
    min_outlier = st.number_input("Minimum Outlier Score", 1.0, step=0.1)

    if st.button("Run Research"):
        long_form = True if content_type=="Long-form" else False
        keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
        videos = fetch_random_videos(keywords, num_results=num_results, long_form=long_form, min_outlier=min_outlier)
        if videos:
            df = pd.DataFrame(videos)
            st.dataframe(df[["Title","Keyword","Views","Outlier Score","Published"]], use_container_width=True)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            st.download_button("Export Excel", data=output.getvalue(),
                               file_name="research_videos.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("No videos found for your criteria.")
