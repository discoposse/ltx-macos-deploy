import streamlit as st
import subprocess
import os
import time
from pathlib import Path

st.set_page_config(
    page_title="LTX Lab",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.sidebar.title("LTX Lab")
st.sidebar.markdown("**macOS Video Generation Studio**")

page = st.sidebar.radio(
    "Navigate",
    ["Generate", "Traces", "Observability", "Library", "Info & Instructions"]
)

st.sidebar.divider()
st.sidebar.caption("All instructions live here. No more scattered docs.")

if page == "Info & Instructions":
    st.title("Welcome to LTX Lab")
    st.markdown("""
    This is the **single interface** for everything LTX-2 on macOS.

    All previous READMEs, launch instructions, prompt tips, and MLflow guidance have been moved here.
    Use the sidebar to explore.

    ### Quick Links
    - **Generate** — Prompt → Video (Distilled or DFR) with live console output
    - **Traces** — MLflow UI with full nested inference traces (port 5001)
    - **Observability** — Live Grafana + Prometheus dashboards
    - **Library** — Your saved prompts and past generations
    - **Info** — This page

    The **Generate** tab now has a real-time console output area modeled after the infinia-mac-lab style.
    """)

    st.info("Run `./start-lab.sh` from the project root to launch everything at once.")

    st.subheader("Prompt Tips")
    st.markdown("""
    - Be specific and cinematic: describe camera movement, lighting, emotion, and timing.
    - For DFR (higher quality): add "highly detailed, cinematic, film grain".
    - Keep personal prompts in the `prompts/` folder — they are gitignored by default.
    """)

elif page == "Generate":
    st.title("Generate Video")
    st.markdown("**Choose mode and describe your scene.** Live console output will appear on the right.")

    col_left, col_right = st.columns([2, 3])

    with col_left:
        mode = st.radio("Pipeline", ["Fast (Distilled)", "High Quality (DFR)"], horizontal=True)
        prompt = st.text_area("Prompt", 
            "A serene Japanese garden at dawn with koi fish swimming in the pond, gentle mist, cinematic lighting, shallow depth of field",
            height=150)
        
        col1, col2 = st.columns(2)
        with col1:
            height = st.slider("Height", 256, 768, 384)
            num_frames = st.slider("Frames", 16, 97, 49)
        with col2:
            width = st.slider("Width", 256, 1280, 640)
            seed = st.number_input("Seed", value=42)

        generate_button = st.button("Generate Video", type="primary")

    with col_right:
        st.subheader("Live Console Output")
        output_placeholder = st.empty()
        video_placeholder = st.empty()

    if generate_button:
        script = "dfr_generate_macos.sh" if "DFR" in mode else "generate_macos.sh"
        output_file = f"output_{int(time.time())}.mp4"
        full_output = ""

        output_placeholder.info("🚀 Starting generation with MLflow tracing...\n")
        
        try:
            process = subprocess.Popen(
                [f"./{script}", prompt, output_file],
                cwd="LTX-2",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output live (console-style like infinia-mac-lab)
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    full_output += output
                    output_placeholder.code(full_output, language="bash")
                    time.sleep(0.02)  # smooth real-time feel
            
            process.wait()
            
            output_path = f"LTX-2/{output_file}"
            if process.returncode == 0 and os.path.exists(output_path):
                output_placeholder.success("✅ Generation complete! Video ready below.")
                video_placeholder.video(output_path)
                st.success(f"Full trace available in MLflow at http://localhost:5001. Video saved as `{output_file}`.")
            else:
                output_placeholder.error(f"Generation failed with code {process.returncode}")
                
        except Exception as e:
            output_placeholder.error(f"Error running generation: {str(e)}")

elif page == "Traces":
    st.title("MLflow Traces")
    st.markdown("All generations are automatically traced with nested spans (text encoder → transformer → VAE → upsampler).")
    
    st.info("MLflow UI is running at http://localhost:5001")
    st.link_button("Open MLflow UI →", "http://localhost:5001")
    st.caption("This shows the full hierarchical inference trace for every generation.")

    st.subheader("Recent Runs")
    st.write("Run history and direct trace links will appear here (connected to mlruns/).")

elif page == "Observability":
    st.title("Observability Dashboard")
    st.markdown("Live metrics, logs, and system snapshots.")

    col1, col2 = st.columns(2)
    with col1:
        st.link_button("Grafana (LTX Dashboard)", "http://localhost:3000")
    with col2:
        st.link_button("Prometheus", "http://localhost:9090")

    st.info("The LTXObserver feeds metrics and logs into these dashboards.")

elif page == "Library":
    st.title("Prompt Library")
    st.markdown("Your saved prompts and past generations live here.")

    prompt_files = list(Path("../prompts").glob("*.txt")) if Path("../prompts").exists() else []
    for f in prompt_files:
        with st.expander(f.name):
            st.text(f.read_text())

    st.caption("Add more prompts in the `prompts/` folder. Personal files stay untracked.")

st.caption("LTX Lab • Live console output modeled after infinia-mac-lab • MLflow on port 5001 • Single launcher (`start-lab.sh`)")
