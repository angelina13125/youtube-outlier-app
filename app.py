import streamlit as st
import pandas as pd
import random
import io
import re
from datetime import datetime
from googleapiclient.discovery import build
import openpyxl  # ✅ fixes the Excel export error

# --------------------------
# API Key Setup
# --------------------------
API_KEY = "AIzaSyBeP68hrblnvgVFkZccoRas44uJSshHTxE"

youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# --------------------------
# Helper Functions
# --------------------------
def normalize_channel_url(url):
    """Cleans channel URL and extracts handle."""
    url = url.strip()
    handle = url.replace("https://", "").replace("http://", "")
    handle = handle.replace("www.youtube.com/", "").replace("youtube.com/", "")
    handle = handle.replace("@", "")
    return handle


def get_channel_videos(channel_handle, max_results=10, min_views=0):
    """Fetches videos from a given channel handle."""
    try:
        search_response = youtube.search().list(
            part="snippet",
            channelId=None,
            q=None,
            type="video",
            maxResults=max_results,
            order="date"
        ).execute()

        videos = []
        for item in search_response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]

            stats_response = youtube.videos().list(
                part="statistics,contentDetails",
                id=video_id
            ).execute()

            if not stats_response["items"]:
                continue

            stats = stats_response["items"][0]["statistics"]
            views = int(stats.get("viewCount", 0))
            if views < min_views:
                continue

            duration = stats_response["items"][0]["contentDetails"]["duration"]
            minutes = parse_duration(duration)
            if minutes < 8:  # Long form filter (default)
                continue

            videos.append({
                "Title": snippet["title"],
                "Views": views,
                "Published": snippet["publishedAt"][:10],
                "Thumbnail": snippet["thumbnails"]["medium"]["url"],
                "Video URL": f"https://www.youtube.com/watch?v={video_id}",
                "Channel": snippet["channelTitle"]
            })

        return videos
    except Exception as e:
        print(f"Error fetching channel {channel_handle}: {e}")
        return []


def parse_duration(duration_str):
    """Convert ISO 8601 duration (e.g. PT10M30S) to minutes."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    total_minutes = int(hours or 0) * 60 + int(minutes or 0) + int(seconds or 0) / 60
    return total_minutes


def fetch_random_videos(keywords, num_results=20, min_views=100000):
    """Fetches random videos for research tab."""
    all_videos = []
    for keyword in keywords:
        res = youtube.search().list(
            part="snippet",
            q=keyword,
            type="video",
            maxResults=50,
            order="relevance"
        ).execute()

        for item in res.get("items", []):
            vid = item["id"]["videoId"]
            snippet = item["snippet"]

            stats = youtube.videos().list(part="statistics,contentDetails", id=vid).execute()
            if not stats["items"]:
                continue

            s = stats["items"][0]
            views = int(s["statistics"].get("viewCount", 0))
            duration = parse_duration(s["contentDetails"]["duration"])
            if views < min_views or duration < 8:
                continue

            all_videos.append({
                "Title": snippet["title"],
                "Views": views,
                "Published": snippet["publishedAt"][:10],
                "Thumbnail": snippet["thumbnails"]["medium"]["url"],
                "Video URL": f"https://www.youtube.com/watch?v={vid}",
                "Keyword": keyword
            })

    random.shuffle(all_videos)
    return all_videos[:num_results]


# --------------------------
# Streamlit Layout
# --------------------------
st.set_page_config(page_title="YouTube Outlier App", layout="wide")
st.title("📊 YouTube Outlier Research & Channel Analyzer")

tab1, tab2 = st.tabs(["Saved Channels", "Outlier Research"])


# --------------------------
# TAB 1: Saved Channels
# --------------------------
with tab1:
    st.header("Saved Channel Outlier Analyzer")

    channel_input = st.text_area(
        "Enter YouTube channel URLs (comma or newline separated):",
        "https://www.youtube.com/@aliabdaal, https://www.youtube.com/@JustinSung"
    )

    num_videos = st.slider("Number of recent videos to fetch per channel", 5, 50, 10)
    min_views = st.number_input("Minimum view count", value=100000, step=10000)
    long_form = st.checkbox("Long-form only (8+ min)", value=True)
    sort_by_outlier = st.checkbox("Sort by Outlier Score (descending)", value=True)

    if st.button("Analyze Channels"):
        channel_urls = re.split(r"[\n,]+", channel_input)
        all_videos = []

        for url in channel_urls:
            handle = normalize_channel_url(url)
            vids = get_channel_videos(handle, num_videos, min_views)
            if vids:
                avg_views = sum(v["Views"] for v in vids) / len(vids)
                for v in vids:
                    v["Outlier Score"] = round(v["Views"] / avg_views, 2)
                    v["Channel"] = handle
                all_videos.extend(vids)
            else:
                st.warning(f"No data for channel: {url}")

        if all_videos:
            df = pd.DataFrame(all_videos)
            if sort_by_outlier:
                df = df.sort_values("Outlier Score", ascending=False)

            st.dataframe(df[["Title", "Channel", "Views", "Outlier Score", "Published"]], use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            st.download_button("Export to Excel", data=output.getvalue(),
                               file_name="channel_outliers.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("No videos matched your filters.")


# --------------------------
# TAB 2: Outlier Research
# --------------------------
with tab2:
    st.header("Outlier Research Tool")

    keyword_input = st.text_area("Enter keywords (comma separated):", "I tried, Top 10")
    num_results = st.slider("Number of random videos", 10, 50, 20)
    min_views_research = st.number_input("Minimum views", value=100000, step=10000)
    min_outlier_score = st.number_input("Minimum Outlier Score", value=1.0, step=0.1)

    if st.button("Run Research"):
        with st.spinner("Running research…"):
            keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
            videos = fetch_random_videos(keywords, num_results=num_results, min_views=min_views_research)

            if videos:
                df = pd.DataFrame(videos)
                avg_views = df["Views"].mean()
                df["Outlier Score"] = round(df["Views"] / avg_views, 2)
                df = df[df["Outlier Score"] >= min_outlier_score]

                st.dataframe(df[["Title", "Keyword", "Views", "Outlier Score", "Published"]], use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False)
                st.download_button("Export to Excel", data=output.getvalue(),
                                   file_name="random_outlier_videos.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("No videos found for your criteria.")

