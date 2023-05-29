import numpy as np
import gradio as gr


def flip_text(x):
    return x[::-1]


def flip_image(x):
    return np.fliplr(x)


with gr.Blocks() as demo:
    gr.Markdown("TextDiffuser.")
    with gr.Tab("Text-to-Image"):
        with gr.Row():
            with gr.Column(scale=1):
                text_input = gr.Textbox(label='Input your prompt here. Please enclose keywords with single quotes.')
                slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
                slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
                slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
                button = gr.Button("Generate")
            with gr.Column(scale=1):
                output = gr.Image()
        button.click(flip_text, inputs=text_input, outputs=output)
        
    with gr.Tab("Text-to-Image-with-Template"):
        with gr.Row():
            with gr.Column(scale=1):
                text_input = gr.Textbox(label='Input your prompt here.')
                template_image = gr.Image(label='Template image')
                slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
                slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
                slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
                button = gr.Button("Generate")
            with gr.Column(scale=1):
                output = gr.Image()
        button.click(flip_text, inputs=text_input, outputs=output)
        
    with gr.Tab("Text-Inpainting"):
        with gr.Row():
            with gr.Column(scale=1):
                text_input = gr.Textbox(label='Input your prompt here.')
                with gr.Row():
                    orig_image = gr.Image(label='Original image')
                    mask_image = gr.Image(label='Mask image')
                slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
                slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
                slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
                button = gr.Button("Generate")
            with gr.Column(scale=1):
                output = gr.Image()
        button.click(flip_text, inputs=text_input, outputs=output)

demo.launch()
