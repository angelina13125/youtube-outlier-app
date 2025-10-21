import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime
import random

# ==========================
# YouTube API Setup
# ==========================
API_KEY = "AIzaSyA3l71bJiM4SW9MPQEp55eTU_BdO8MUX1A"
youtube = build("youtube", "v3", developerKey=API_KEY)

# ==========================
# Helper Functions
# ==========================
def get_channel_stats(channel_id):
    res = youtube.channels().list(
        part="statistics,snippet",
        id=channel_id
    ).execute()
    item = res['items'][0]
    stats = item['statistics']
    snippet = item['snippet']
    return {
        "channel_title": snippet['title'],
        "subs": int(stats.get('subscriberCount', 0)),
        "total_views": int(stats.get('viewCount', 0)),
        "video_count": int(stats.get('videoCount', 0))
    }

def get_videos_from_channel(channel_id, max_results=50, min_views=0):
    res = youtube.search().list(
        part="id,snippet",
        channelId=channel_id,
        maxResults=max_results,
        type="video",
        order="date"
    ).execute()
    videos = []
    for item in res.get("items", []):
        vid = item["id"]["videoId"]
        snippet = item["snippet"]
        stats = youtube.videos().list(part="statistics", id=vid).execute()['items'][0]['statistics']
        views = int(stats.get('viewCount', 0))
        if views < min_views:
            continue
        videos.append({
            "Video ID": vid,
            "Title": snippet['title'],
            "Thumbnail": snippet['thumbnails']['medium']['url'],
            "Published": snippet['publishedAt'],
            "Video URL": f"https://www.youtube.com/watch?v={vid}",
            "Views": views
        })
    return videos

def calculate_outlier_score(video_views, channel_avg):
    if channel_avg == 0:
        return 0
    return round(video_views / channel_avg, 2)

def fetch_random_videos(keywords, num_results=20, min_views=100000):
    all_videos = []
    for _ in range(num_results):
        kw = random.choice(keywords)
        res = youtube.search().list(
            part="id,snippet",
            q=kw,
            type="video",
            maxResults=1,
            order="viewCount"
        ).execute()
        for item in res.get("items", []):
            vid = item["id"]["videoId"]
            snippet = item["snippet"]
            stats = youtube.videos().list(part="statistics", id=vid).execute()['items'][0]['statistics']
            views = int(stats.get('viewCount', 0))
            if views < min_views:
                continue
            all_videos.append({
                "Video ID": vid,
                "Title": snippet['title'],
                "Thumbnail": snippet['thumbnails']['medium']['url'],
                "Published": snippet['publishedAt'],
                "Video URL": f"https://www.youtube.com/watch?v={vid}",
                "Views": views
            })
    return all_videos

# ==========================
# Streamlit Layout
# ==========================
st.set_page_config(page_title="YouTube Outlier Finder", layout="wide")
st.title("🎯 YouTube Outlier Finder")

tab1, tab2 = st.tabs(["Saved Channels", "Research"])

# --------------------------
# Saved Channels Tab
# --------------------------
with tab1:
    st.header("Saved Channels Tool")
    channel_input = st.text_area("Enter one or more YouTube channel IDs (comma separated):")
    max_results = st.slider("Number of videos per channel", 10, 50, 20)
    min_views = st.number_input("Minimum views per video", value=0, step=1000)
    sort_by = st.selectbox("Sort videos by", ["Views", "Outlier Score", "Published"])
    
    if st.button("Fetch Saved Channel Videos"):
        all_videos = []
        for cid in [c.strip() for c in channel_input.split(",") if c.strip()]:
            stats = get_channel_stats(cid)
            vids = get_videos_from_channel(cid, max_results=max_results, min_views=min_views)
            # calculate outlier score
            channel_avg = stats['total_views'] / max(stats['video_count'],1)
            for v in vids:
                v['Outlier Score'] = calculate_outlier_score(v['Views'], channel_avg)
                v['Channel'] = stats['channel_title']
            all_videos.extend(vids)
        
        if all_videos:
            df = pd.DataFrame(all_videos)
            if sort_by == "Views":
                df = df.sort_values(by="Views", ascending=False)
            elif sort_by == "Outlier Score":
                df = df.sort_values(by="Outlier Score", ascending=False)
            elif sort_by == "Published":
                df = df.sort_values(by="Published", ascending=False)
            
            # Display in grid
            for i in range(0, len(df), 4):
                cols = st.columns(4)
                for j, col in enumerate(cols):
                    if i+j < len(df):
                        video = df.iloc[i+j]
                        col.image(video['Thumbnail'])
                        col.markdown(f"[{video['Title']}]({video['Video URL']})")
                        col.write(f"Channel: {video['Channel']}")
                        col.write(f"Views: {video['Views']}, Outlier: {video['Outlier Score']}")
                        col.write(f"Published: {video['Published']}")
            
            # Export to Excel
            st.download_button("Export to Excel", df.to_excel(index=False), file_name="saved_channel_videos.xlsx")
        else:
            st.warning("No videos found.")

# --------------------------
# Research Tab
# --------------------------
with tab2:
    st.header("Outlier Research Tool")
    keyword_input = st.text_area("Enter keywords (comma separated):", "I tried, My story, Top 10")
    num_results = st.slider("Number of random videos", 10, 50, 20)
    min_views_research = st.number_input("Minimum views", value=100000, step=10000)
    
    if st.button("Generate Random Outlier Videos"):
        keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]
        all_videos = fetch_random_videos(keywords, num_results=num_results, min_views=min_views_research)
        if all_videos:
            df = pd.DataFrame(all_videos)
            # Display in grid
            for i in range(0, len(df), 4):
                cols = st.columns(4)
                for j, col in enumerate(cols):
                    if i+j < len(df):
                        video = df.iloc[i+j]
                        col.image(video['Thumbnail'])
                        col.markdown(f"[{video['Title']}]({video['Video URL']})")
                        col.write(f"Views: {video['Views']}")
                        col.write(f"Published: {video['Published']}")
            
            st.download_button("Export to Excel", df.to_excel(index=False), file_name="random_outlier_videos.xlsx")
        else:
            st.warning("No videos found.")
