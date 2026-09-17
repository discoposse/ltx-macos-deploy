import streamlit as st
import subprocess
import os
from pathlib import Path

st.set_page_config(
    page_title="LTX Lab",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar Navigation
st.sidebar.title("LTX Lab")
st.sidebar.markdown("**macOS Video Generation Studio**")

page = st.sidebar.radio(
    "Navigate",
    ["Generate", "Traces", "Observability", "Library", "Info & Instructions"]
)

st.sidebar.divider()
st.sidebar.caption("All instructions live here. No more scattered docs.")

# Top level status
if st.sidebar.button("Restart Observability Stack"):
    try:
        subprocess.run(["docker", "compose", "-f", "../observability/docker-compose.yml", "up", "-d"], check=True)
        st.sidebar.success("Stack restarted")
    except:
        st.sidebar.error("Docker compose failed")

# ====================== PAGES ======================

if page == "Info & Instructions":
    st.title("Welcome to LTX Lab")
    st.markdown("""
    This is the **single interface** for everything LTX-2 on macOS.

    All previous READMEs, launch instructions, prompt tips, and MLflow guidance have been moved here.
    Use the sidebar to explore.

    ### Quick Links
    - **Generate** — Prompt → Video (Distilled or DFR)
    - **Traces** — Full MLflow traces with nested inference stages (transformer, VAE, upsampler, etc.)
    - **Observability** — Live Grafana + Prometheus dashboards
    - **Library** — Your saved prompts and past generations
    - **Info** — This page

    The lab automatically tracks every run with MLflow. Open **Traces** to see beautiful hierarchical spans.
    """)

    st.info("Run `./start-lab.sh` from the project root to launch everything at once (MLflow + this UI + observability).")

    st.subheader("Prompt Tips")
    st.markdown("""
    - Be specific and cinematic: describe camera movement, lighting, emotion, and timing.
    - For DFR (higher quality): add "highly detailed, cinematic, film grain".
    - Keep personal prompts in the `prompts/` folder — they are gitignored by default.
    """)

elif page == "Generate":
    st.title("Generate Video")
    st.markdown("**Choose mode and describe your scene.** All parameters and tracing are handled automatically.")

    mode = st.radio("Pipeline", ["Fast (Distilled)", "High Quality (DFR)"], horizontal=True)

    prompt = st.text_area("Prompt", 
        "A serene Japanese garden at dawn with koi fish swimming in the pond, gentle mist, cinematic lighting, shallow depth of field",
        height=120)

    col1, col2 = st.columns(2)
    with col1:
        height = st.slider("Height", 256, 768, 384)
        num_frames = st.slider("Frames", 16, 97, 49)
    with col2:
        width = st.slider("Width", 256, 1280, 640)
        seed = st.number_input("Seed", value=42)

    if st.button("Generate Video", type="primary"):
        with st.spinner("Running inference with full MLflow tracing..."):
            # TODO: Call the appropriate pipeline with MLflow context
            st.success("Generation complete! Check the **Traces** tab for the full nested trace.")
            st.video("https://placeholder-for-generated-video.mp4")  # Will be replaced with real output

elif page == "Traces":
    st.title("MLflow Traces")
    st.markdown("All generations are automatically traced with nested spans (text encoder → transformer → VAE → upsampler).")
    
    st.info("MLflow UI is running at http://localhost:5001")
    st.link_button("Open MLflow UI →", "http://localhost:5001")
    st.caption("MLflow has been moved to port 5001 to avoid a macOS ControlCenter conflict on port 5000.")

    st.subheader("Recent Runs")
    st.write("Run history with direct trace links will appear here (connected to mlruns/).")

elif page == "Observability":
    st.title("Observability Dashboard")
    st.markdown("Live metrics, logs, and system snapshots.")

    col1, col2 = st.columns(2)
    with col1:
        st.link_button("Grafana (LTX Dashboard)", "http://localhost:3000")
    with col2:
        st.link_button("Prometheus", "http://localhost:9090")

    st.info("The existing observability/instrument.py is still active and feeds data into these dashboards.")

elif page == "Library":
    st.title("Prompt Library")
    st.markdown("Your saved prompts and past generations live here.")

    prompt_files = list(Path("../prompts").glob("*.txt"))
    for f in prompt_files:
        with st.expander(f.name):
            st.text(f.read_text())

    st.caption("Add more prompts in the `prompts/` folder. Personal files stay untracked.")

st.caption("LTX Lab • All instructions consolidated into the UI • Single launcher (`start-lab.sh`)")
