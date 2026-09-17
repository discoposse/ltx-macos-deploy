import gradio as gr
import subprocess
import os
import time
from pathlib import Path
import threading

# Global state
current_output = ""
current_video = None
is_generating = False

def generate_video(prompt, mode):
    global current_output, current_video, is_generating
    
    if is_generating:
        return "Generation already in progress...", None
    
    is_generating = True
    current_output = "🚀 Starting generation...\n"
    script = "dfr_generate_macos.sh" if "DFR" in mode else "generate_macos.sh"
    output_file = f"output_{int(time.time())}.mp4"
    
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
        
        # Stream output live
        for line in process.stdout:
            current_output += line
            yield current_output, None  # Update console live
        
        process.wait()
        
        output_path = f"LTX-2/{output_file}"
        if process.returncode == 0 and os.path.exists(output_path):
            current_output += f"\n✅ Generation complete! Video saved as {output_file}\n"
            current_video = output_path
            yield current_output, output_path
        else:
            current_output += f"\n❌ Generation failed with code {process.returncode}\n"
            yield current_output, None
            
    except Exception as e:
        current_output += f"\n💥 Error: {str(e)}\n"
        yield current_output, None
    finally:
        is_generating = False

def clear_output():
    global current_output, current_video
    current_output = ""
    current_video = None
    return "", None

with gr.Blocks(title="LTX Lab", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# LTX Lab\n**macOS Video Generation Studio with Live Console**")
    
    with gr.Tabs():
        with gr.Tab("Generate"):
            with gr.Row():
                with gr.Column(scale=2):
                    prompt = gr.Textbox(
                        label="Prompt",
                        value="A serene Japanese garden at dawn with koi fish swimming in the pond, gentle mist, cinematic lighting, shallow depth of field",
                        lines=8
                    )
                    mode = gr.Radio(["Fast (Distilled)", "High Quality (DFR)"], label="Pipeline", value="Fast (Distilled)")
                    
                    with gr.Row():
                        height = gr.Slider(256, 768, value=384, step=64, label="Height")
                        width = gr.Slider(256, 1280, value=640, step=64, label="Width")
                    with gr.Row():
                        num_frames = gr.Slider(16, 97, value=49, step=1, label="Frames")
                        seed = gr.Number(value=42, label="Seed")
                    
                    generate_btn = gr.Button("Generate Video", variant="primary", size="large")
                    clear_btn = gr.Button("Clear Output")
                
                with gr.Column(scale=3):
                    gr.Markdown("### Live Console Output")
                    console = gr.Textbox(
                        label="",
                        lines=20,
                        max_lines=30,
                        show_copy_button=True,
                        value="Click Generate to start. Output will stream here in real-time (like the infinia-mac-lab console).",
                        elem_classes=["console"]
                    )
                    output_video = gr.Video(label="Generated Video", visible=True)
        
        with gr.Tab("Traces"):
            gr.Markdown("### MLflow Traces")
            gr.Markdown("Full nested inference traces (text encoder → transformer stages → VAE → upsampler) are available in MLflow.")
            gr.Link("Open MLflow UI →", "http://localhost:5001", size="lg")
            gr.Markdown("All generations are automatically wrapped in MLflow runs.")
        
        with gr.Tab("Observability"):
            gr.Markdown("### Live Dashboards")
            with gr.Row():
                gr.Link("Grafana Dashboard", "http://localhost:3000", size="lg")
                gr.Link("Prometheus Metrics", "http://localhost:9090", size="lg")
            gr.Markdown("The LTXObserver pushes metrics and logs to these dashboards.")
        
        with gr.Tab("Library"):
            gr.Markdown("### Prompt Library")
            gr.Markdown("Your personal prompts live in the `prompts/` folder (gitignored by default).")
            gr.Markdown("Past generations and experiments are stored in `mlruns/` and `observability/runs/`.")
        
        with gr.Tab("Info"):
            gr.Markdown("""
            # LTX Lab
            
            This is a clean, focused macOS lab for LTX-2 video generation.
            
            **All instructions are now in the UI.** No more scattered READMEs.
            
            - Uses your tuned `generate_macos.sh` and `dfr_generate_macos.sh` scripts
            - Real-time streaming console (no fake instant success)
            - Full MLflow tracing on port 5001
            - Observability stack (Grafana + Prometheus + Loki)
            
            Run `./start-lab.sh` to launch everything.
            """)

    # Wire up the generation
    generate_btn.click(
        fn=generate_video,
        inputs=[prompt, mode],
        outputs=[console, output_video],
        show_progress=True
    )
    
    clear_btn.click(
        fn=clear_output,
        outputs=[console, output_video]
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=8501,
        share=False,
        show_error=True
    )
