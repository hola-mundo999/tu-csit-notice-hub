import streamlit as st
import time
from database import init_db, save_notice, get_notices
from scraper import TUScraper
from notifier import TelegramNotifier

st.set_page_config(
    page_title="TU CSIT Notice Hub | Samyog",
    page_icon="📢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .stApp {
        background-color: #0b0d13;
        color: #f1f5f9;
    }
    .header-panel {
        background: linear-gradient(135deg, rgba(14,165,233,0.15) 0%, rgba(99,102,241,0.15) 100%);
        border: 1px solid rgba(14,165,233,0.3);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 24px;
    }
    .notice-card {
        background: rgba(15,23,42,0.7);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 14px;
        transition: all 0.2s;
    }
    .notice-card:hover {
        border-color: rgba(14,165,233,0.4);
    }
    .urgent-badge {
        display: inline-block;
        background: rgba(239,68,68,0.2);
        color: #f87171;
        border: 1px solid rgba(239,68,68,0.3);
        padding: 2px 10px;
        border-radius: 99px;
        font-size: 11px;
        font-family: monospace;
    }
    .cat-badge {
        display: inline-block;
        background: rgba(14,165,233,0.15);
        color: #38bdf8;
        border: 1px solid rgba(14,165,233,0.3);
        padding: 2px 10px;
        border-radius: 99px;
        font-size: 11px;
        font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Database
init_db()

# Auto-seed initial notices if database is empty
initial_notices = get_notices()
if not initial_notices:
    for n in TUScraper.get_curated_csit_notices():
        save_notice(n)
    initial_notices = get_notices()

# Header
st.markdown("""
<div class="header-panel">
    <div style="font-family: monospace; font-size: 11px; color: #38bdf8; margin-bottom: 6px;">
        TRIBHUVAN UNIVERSITY · INSTITUTE OF SCIENCE & TECHNOLOGY (IOST)
    </div>
    <h1 style="margin: 0; font-size: 32px; font-weight: 800; color: white;">
        📢 TU CSIT Notice & Routine Alert Hub
    </h1>
    <p style="margin: 8px 0 0 0; color: #94a3b8; font-size: 14px;">
        Automated web scraper and notification pipeline for BSc CSIT exam routines, results, and academic notices.
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### 🔍 Search & Filters")
    category_filter = st.selectbox(
        "Notice Category",
        options=["All", "Exam Routine", "Results", "Form Fill Up", "General Notice"]
    )

    semester_filter = st.selectbox(
        "Semester",
        options=["All Semesters", "1st Sem", "2nd Sem", "3rd Sem", "4th Sem", "5th Sem", "6th Sem", "7th Sem", "8th Sem"]
    )

    search_query = st.text_input("Keyword Search", placeholder="e.g. 2079, Routine, Result...")

    st.markdown("---")
    st.markdown("### 🔄 Scraper Controls")
    if st.button("🚀 Scrape & Sync Live Notices", type="primary"):
        with st.spinner("Scraping Tribhuvan University notice board..."):
            scraped = TUScraper.fetch_live_notices()
            new_count = 0
            for item in scraped:
                if save_notice(item):
                    new_count += 1
            st.success(f"Sync complete! Added {new_count} new notices.")
            time.sleep(0.5)
            st.rerun()

    st.markdown("---")
    st.markdown("👨‍💻 **Architected by:** Samyog")
    st.caption("Backend Automation & Web Scraping Project")

# Metrics Overview
all_cached = get_notices()
routine_count = sum(1 for n in all_cached if n["category"] == "Exam Routine")
results_count = sum(1 for n in all_cached if n["category"] == "Results")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Total Notices", len(all_cached))
with m2:
    st.metric("Exam Routines", routine_count)
with m3:
    st.metric("Results Published", results_count)
with m4:
    st.metric("Database Status", "SQLite Active")

st.markdown("<br>", unsafe_allow_html=True)

# Filtered Notices
filtered_notices = get_notices(
    category=category_filter,
    semester=semester_filter,
    search_query=search_query
)

tab1, tab2 = st.tabs(["📋 Notice Feed", "📱 Telegram Alert Simulator"])

with tab1:
    if filtered_notices:
        for n in filtered_notices:
            urgent_html = '<span class="urgent-badge">🚨 URGENT</span>' if n["is_urgent"] else ''
            st.markdown(f"""
            <div class="notice-card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div>
                        <span class="cat-badge">{n['category']}</span>
                        <span style="font-size: 11px; font-family: monospace; color: #94a3b8; margin-left: 8px;">
                            {n['semester']}
                        </span>
                        {urgent_html}
                    </div>
                    <span style="font-size: 12px; color: #64748b; font-family: monospace;">
                        {n['publish_date']}
                    </span>
                </div>
                <h3 style="color: white; font-size: 17px; margin: 4px 0 10px 0;">
                    {n['title']}
                </h3>
                <div style="display: flex; gap: 12px; align-items: center; margin-top: 10px;">
                    <a href="{n['url']}" target="_blank" style="font-size: 12px; color: #38bdf8; text-decoration: none;">
                        🔗 View Official TU Document &rarr;
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No notices match the selected filter criteria.")

with tab2:
    st.subheader("Simulated Telegram Broadcast Preview")
    st.caption("This is how notices appear formatted when dispatched to student Telegram channels:")

    if filtered_notices:
        sample_notice = filtered_notices[0]
        preview_text = TelegramNotifier.format_message(sample_notice)
        st.text_area("Telegram Markdown Message Payload", value=preview_text, height=220, disabled=True)

        if st.button("📢 Simulate Channel Broadcast"):
            result = TelegramNotifier.send_telegram_alert(sample_notice)
            st.success(result["message"])
    else:
        st.write("No notices available to preview.")
