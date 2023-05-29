# ------------------------------------------
# TextDiffuser: Diffusion Models as Text Painters
# Paper Link: https://arxiv.org/abs/2305.10855
# Code Link: https://github.com/microsoft/unilm/tree/master/textdiffuser
# Copyright (c) Microsoft Corporation.
# This file provides the inference script.
# ------------------------------------------

import os
import zipfile


os.system('wget https://layoutlm.blob.core.windows.net/textdiffuser/textdiffuser-ckpt.zip')
os.system('wget https://layoutlm.blob.core.windows.net/textdiffuser/Arial.ttf')
# 打开 zip 文件
with zipfile.ZipFile('textdiffuser-ckpt.zip', 'r') as zip_ref:
    zip_ref.extractall('.')
    
    
os.system('echo finish')
os.system('ls -a')


import cv2
import random
import logging
import argparse
import numpy as np

from pathlib import Path
from tqdm.auto import tqdm
from typing import Optional
from packaging import version
from termcolor import colored
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance # import for visualization
from huggingface_hub import HfFolder, Repository, create_repo, whoami

import datasets
from datasets import load_dataset
from datasets import disable_caching

import torch
import torch.utils.checkpoint
import torch.nn.functional as F

import accelerate
from accelerate import Accelerator
from accelerate.logging import get_logger
from accelerate.utils import ProjectConfiguration, set_seed

import diffusers
from diffusers import AutoencoderKL, DDPMScheduler, StableDiffusionPipeline, UNet2DConditionModel 
from diffusers.optimization import get_scheduler
from diffusers.training_utils import EMAModel
from diffusers.utils import check_min_version, deprecate
from diffusers.utils.import_utils import is_xformers_available

import transformers
from transformers import CLIPTextModel, CLIPTokenizer

from util import segmentation_mask_visualization, make_caption_pil, combine_image, transform_mask, filter_segmentation_mask, inpainting_merge_image
from model.layout_generator import get_layout_from_prompt
from model.text_segmenter.unet import UNet


disable_caching()
check_min_version("0.15.0.dev0")
logger = get_logger(__name__, log_level="INFO")


def parse_args():
    parser = argparse.ArgumentParser(description="Simple example of a training script.")
    parser.add_argument(
        "--pretrained_model_name_or_path", 
        type=str,
        default='runwayml/stable-diffusion-v1-5', # no need to modify this  
        help="Path to pretrained model or model identifier from huggingface.co/models. Please do not modify this.",
    )
    parser.add_argument(
        "--revision",
        type=str,
        default=None,
        required=False,
        help="Revision of pretrained model identifier from huggingface.co/models.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="text-to-image",
        # required=True,
        choices=["text-to-image", "text-to-image-with-template", "text-inpainting"],
        help="Three modes can be used.",
    )
    parser.add_argument(
        "--prompt", 
        type=str,
        default="",
        # required=True,
        help="The text prompts provided by users.",
    )
    parser.add_argument(
        "--template_image", 
        type=str,
        default="",
        help="The template image should be given when using 【text-to-image-with-template】 mode.",
    )
    parser.add_argument(
        "--original_image", 
        type=str,
        default="",
        help="The original image should be given when using 【text-inpainting】 mode.",
    )
    parser.add_argument(
        "--text_mask", 
        type=str,
        default="",
        help="The text mask should be given when using 【text-inpainting】 mode.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="output",
        help="The output directory where the model predictions and checkpoints will be written.",
    )
    parser.add_argument(
        "--cache_dir",
        type=str,
        default=None,
        help="The directory where the downloaded models and datasets will be stored.",
    )
    parser.add_argument(
        "--seed", 
        type=int, 
        default=None, 
        help="A seed for reproducible training."
    )
    parser.add_argument(
        "--resolution",
        type=int,
        default=512,
        help=(
            "The resolution for input images, all the images in the train/validation dataset will be resized to this"
            " resolution"
        ),
    )
    parser.add_argument(
        "--classifier_free_scale", 
        type=float,
        default=7.5, # following stable diffusion (https://github.com/CompVis/stable-diffusion)
        help="Classifier free scale following https://arxiv.org/abs/2207.12598.",
    )
    parser.add_argument(
        "--drop_caption", 
        action="store_true", 
        help="Whether to drop captions during training following https://arxiv.org/abs/2207.12598.."
    )
    parser.add_argument(
        "--dataloader_num_workers",
        type=int,
        default=0, 
        help="Number of subprocesses to use for data loading. 0 means that the data will be loaded in the main process."
    )
    parser.add_argument(
        "--push_to_hub", 
        action="store_true", 
        help="Whether or not to push the model to the Hub."
    )
    parser.add_argument(
        "--hub_token", 
        type=str, 
        default=None, 
        help="The token to use to push to the Model Hub."
    )
    parser.add_argument(
        "--hub_model_id",
        type=str,
        default=None,
        help="The name of the repository to keep in sync with the local `output_dir`.",
    )
    parser.add_argument(
        "--logging_dir",
        type=str,
        default="logs",
        help=(
            "[TensorBoard](https://www.tensorflow.org/tensorboard) log directory. Will default to"
            " *output_dir/runs/**CURRENT_DATETIME_HOSTNAME***."
        ),
    )
    parser.add_argument(
        "--mixed_precision",
        type=str,
        default='fp16',
        choices=["no", "fp16", "bf16"],
        help=(
            "Whether to use mixed precision. Choose between fp16 and bf16 (bfloat16). Bf16 requires PyTorch >="
            " 1.10.and an Nvidia Ampere GPU.  Default to the value of accelerate config of the current system or the"
            " flag passed with the `accelerate.launch` command. Use this argument to override the accelerate config."
        ),
    )
    parser.add_argument(
        "--report_to", 
        type=str,
        default="tensorboard",
        help=(
            'The integration to report the results and logs to. Supported platforms are `"tensorboard"`'
            ' (default), `"wandb"` and `"comet_ml"`. Use `"all"` to report to all integrations.'
        ),
    )
    parser.add_argument(
        "--local_rank", 
        type=int, 
        default=-1, 
        help="For distributed training: local_rank"
    )
    parser.add_argument(
        "--checkpointing_steps",
        type=int,
        default=500, 
        help=(
            "Save a checkpoint of the training state every X updates. These checkpoints are only suitable for resuming"
            " training using `--resume_from_checkpoint`."
        ),
    )
    parser.add_argument(
        "--checkpoints_total_limit",
        type=int,
        default=5,
        help=(
            "Max number of checkpoints to store. Passed as `total_limit` to the `Accelerator` `ProjectConfiguration`."
            " See Accelerator::save_state https://huggingface.co/docs/accelerate/package_reference/accelerator#accelerate.Accelerator.save_state"
            " for more docs"
        ),
    )
    parser.add_argument(
        "--resume_from_checkpoint",
        type=str,
        default='textdiffuser-ckpt/diffusion_backbone', # should be specified during inference
        help=(
            "Whether training should be resumed from a previous checkpoint. Use a path saved by"
            ' `--checkpointing_steps`, or `"latest"` to automatically select the last available checkpoint.'
        ),
    )
    parser.add_argument(
        "--enable_xformers_memory_efficient_attention", 
        action="store_true", 
        help="Whether or not to use xformers."
    )
    parser.add_argument(
        "--font_path", 
        type=str, 
        default='Arial.ttf', 
        help="The path of font for visualization."
    )
    parser.add_argument(
        "--sample_steps", 
        type=int, 
        default=50, # following stable diffusion (https://github.com/CompVis/stable-diffusion)
        help="Diffusion steps for sampling."
    )
    parser.add_argument(
        "--vis_num", 
        type=int, 
        default=4, # please decreases the number if out-of-memory error occurs
        help="Number of images to be sample. Please decrease it when encountering out of memory error."
    )
    parser.add_argument(
        "--binarization", 
        action="store_true", 
        help="Whether to binarize the template image."
    )
    parser.add_argument(
        "--use_pillow_segmentation_mask", 
        type=bool,
        default=True, 
        help="In the 【text-to-image】 mode, please specify whether to use the segmentation masks provided by PILLOW"
    )
    parser.add_argument(
        "--character_segmenter_path", 
        type=str,
        default='textdiffuser-ckpt/text_segmenter.pth',
        help="checkpoint of character-level segmenter"
    )
    args = parser.parse_args()
    
    print(f'{colored("[√]", "green")} Arguments are loaded.')
    print(args)
    
    env_local_rank = int(os.environ.get("LOCAL_RANK", -1))
    if env_local_rank != -1 and env_local_rank != args.local_rank:
        args.local_rank = env_local_rank

    return args



def get_full_repo_name(model_id: str, organization: Optional[str] = None, token: Optional[str] = None):
    if token is None:
        token = HfFolder.get_token()
    if organization is None:
        username = whoami(token)["name"]
        return f"{username}/{model_id}"
    else:
        return f"{organization}/{model_id}"



args = parse_args()
# args.prompt = prompt # 在这里修改prompt
# If passed along, set the training seed now.

# print(f'{colored("[√]", "green")} Seed is set to {seed}.')

logging_dir = os.path.join(args.output_dir, args.logging_dir)
# sub_output_dir = f"{args.prompt}_[{args.mode.upper()}]_[SEED-{seed}]"

print(f'{colored("[√]", "green")} Logging dir is set to {logging_dir}.')

accelerator_project_config = ProjectConfiguration(total_limit=args.checkpoints_total_limit)

accelerator = Accelerator(
    gradient_accumulation_steps=1,
    mixed_precision=args.mixed_precision,
    log_with=args.report_to,
    logging_dir=logging_dir,
    project_config=accelerator_project_config,
)

# Make one log on every process with the configuration for debugging.
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger.info(accelerator.state, main_process_only=False)
if accelerator.is_local_main_process:
    datasets.utils.logging.set_verbosity_warning()
    transformers.utils.logging.set_verbosity_warning()
    diffusers.utils.logging.set_verbosity_info()
else:
    datasets.utils.logging.set_verbosity_error()
    transformers.utils.logging.set_verbosity_error()
    diffusers.utils.logging.set_verbosity_error()

# Handle the repository creation
if accelerator.is_main_process:
    if args.push_to_hub:
        if args.hub_model_id is None:
            repo_name = get_full_repo_name(Path(args.output_dir).name, token=args.hub_token)
        else:
            repo_name = args.hub_model_id
        create_repo(repo_name, exist_ok=True, token=args.hub_token)
        repo = Repository(args.output_dir, clone_from=repo_name, token=args.hub_token)

        with open(os.path.join(args.output_dir, ".gitignore"), "w+") as gitignore:
            if "step_*" not in gitignore:
                gitignore.write("step_*\n")
            if "epoch_*" not in gitignore:
                gitignore.write("epoch_*\n")
    elif args.output_dir is not None:
        os.makedirs(args.output_dir, exist_ok=True)
        print(args.output_dir)

# Load scheduler, tokenizer and models.
tokenizer = CLIPTokenizer.from_pretrained(
    args.pretrained_model_name_or_path, subfolder="tokenizer", revision=args.revision
)
text_encoder = CLIPTextModel.from_pretrained(
    args.pretrained_model_name_or_path, subfolder="text_encoder", revision=args.revision
)
vae = AutoencoderKL.from_pretrained(args.pretrained_model_name_or_path, subfolder="vae", revision=args.revision).cuda()
unet = UNet2DConditionModel.from_pretrained(
    args.resume_from_checkpoint, subfolder="unet", revision=None 
).cuda() 

# Freeze vae and text_encoder
vae.requires_grad_(False)
text_encoder.requires_grad_(False)

if args.enable_xformers_memory_efficient_attention:
    if is_xformers_available():
        import xformers

        xformers_version = version.parse(xformers.__version__)
        if xformers_version == version.parse("0.0.16"):
            logger.warn(
                "xFormers 0.0.16 cannot be used for training in some GPUs. If you observe problems during training, please update xFormers to at least 0.0.17. See https://huggingface.co/docs/diffusers/main/en/optimization/xformers for more details."
            )
        unet.enable_xformers_memory_efficient_attention()
    else:
        raise ValueError("xformers is not available. Make sure it is installed correctly")

# `accelerate` 0.16.0 will have better support for customized saving
if version.parse(accelerate.__version__) >= version.parse("0.16.0"):
    # create custom saving & loading hooks so that `accelerator.save_state(...)` serializes in a nice format
    def save_model_hook(models, weights, output_dir):
        
        for i, model in enumerate(models):
            model.save_pretrained(os.path.join(output_dir, "unet"))

            # make sure to pop weight so that corresponding model is not saved again
            weights.pop()

    def load_model_hook(models, input_dir):
        
        for i in range(len(models)):
            # pop models so that they are not loaded again
            model = models.pop()

            # load diffusers style into model
            load_model = UNet2DConditionModel.from_pretrained(input_dir, subfolder="unet")
            model.register_to_config(**load_model.config)

            model.load_state_dict(load_model.state_dict())
            del load_model

    accelerator.register_save_state_pre_hook(save_model_hook)
    accelerator.register_load_state_pre_hook(load_model_hook)


# setup schedulers                    
scheduler = DDPMScheduler.from_pretrained(args.pretrained_model_name_or_path, subfolder="scheduler") 
# sample_num = args.vis_num

def text_to_image(prompt,slider_step,slider_batch,slider_seed):

    args.prompt = prompt # 在这里修改prompt
    sample_num = slider_batch
    # If passed along, set the training seed now.
    seed = slider_seed
    set_seed(seed)
    scheduler.set_timesteps(slider_step) 

    noise = torch.randn((sample_num, 4, 64, 64)).to("cuda")  # (b, 4, 64, 64)
    input = noise # (b, 4, 64, 64)

    captions = [args.prompt] * sample_num
    captions_nocond = [""] * sample_num
    print(f'{colored("[√]", "green")} Prompt is loaded: {args.prompt}.')
    
    # encode text prompts
    inputs = tokenizer(
        captions, max_length=tokenizer.model_max_length, padding="max_length", truncation=True, return_tensors="pt"
    ).input_ids # (b, 77)
    encoder_hidden_states = text_encoder(inputs)[0].cuda() # (b, 77, 768)
    print(f'{colored("[√]", "green")} encoder_hidden_states: {encoder_hidden_states.shape}.')

    inputs_nocond = tokenizer(
        captions_nocond, max_length=tokenizer.model_max_length, padding="max_length", truncation=True, return_tensors="pt"
    ).input_ids # (b, 77)
    encoder_hidden_states_nocond = text_encoder(inputs_nocond)[0].cuda() # (b, 77, 768)
    print(f'{colored("[√]", "green")} encoder_hidden_states_nocond: {encoder_hidden_states_nocond.shape}.')

    # load character-level segmenter
    segmenter = UNet(3, 96, True).cuda()
    segmenter = torch.nn.DataParallel(segmenter)
    segmenter.load_state_dict(torch.load(args.character_segmenter_path))
    segmenter.eval()
    print(f'{colored("[√]", "green")} Text segmenter is successfully loaded.')

    #### text-to-image ####
    if args.mode == 'text-to-image':    
        render_image, segmentation_mask_from_pillow = get_layout_from_prompt(args)
        
        segmentation_mask = torch.Tensor(np.array(segmentation_mask_from_pillow)).cuda() # (512, 512)
    
        segmentation_mask = filter_segmentation_mask(segmentation_mask)
        segmentation_mask = torch.nn.functional.interpolate(segmentation_mask.unsqueeze(0).unsqueeze(0).float(), size=(256, 256), mode='nearest')
        segmentation_mask = segmentation_mask.squeeze(1).repeat(sample_num, 1, 1).long().to('cuda') # (1, 1, 256, 256)
        print(f'{colored("[√]", "green")} character-level segmentation_mask: {segmentation_mask.shape}.')
        
        feature_mask = torch.ones(sample_num, 1, 64, 64).to('cuda') # (b, 1, 64, 64)
        masked_image = torch.zeros(sample_num, 3, 512, 512).to('cuda') # (b, 3, 512, 512)
        masked_feature = vae.encode(masked_image).latent_dist.sample() # (b, 4, 64, 64)
        masked_feature = masked_feature * vae.config.scaling_factor 
        print(f'{colored("[√]", "green")} feature_mask: {feature_mask.shape}.')
        print(f'{colored("[√]", "green")} masked_feature: {masked_feature.shape}.')


    # diffusion process
    intermediate_images = []
    for t in tqdm(scheduler.timesteps):
        with torch.no_grad():
            noise_pred_cond = unet(sample=input, timestep=t, encoder_hidden_states=encoder_hidden_states, segmentation_mask=segmentation_mask, feature_mask=feature_mask, masked_feature=masked_feature).sample # b, 4, 64, 64
            noise_pred_uncond = unet(sample=input, timestep=t, encoder_hidden_states=encoder_hidden_states_nocond, segmentation_mask=segmentation_mask, feature_mask=feature_mask, masked_feature=masked_feature).sample # b, 4, 64, 64
            noisy_residual = noise_pred_uncond + args.classifier_free_scale * (noise_pred_cond - noise_pred_uncond) # b, 4, 64, 64     
            prev_noisy_sample = scheduler.step(noisy_residual, t, input).prev_sample 
            input = prev_noisy_sample
            intermediate_images.append(prev_noisy_sample)
            
    # decode and visualization
    input = 1 / vae.config.scaling_factor * input 
    sample_images = vae.decode(input.float(), return_dict=False)[0] # (b, 3, 512, 512)

    image_pil = render_image.resize((512,512))
    segmentation_mask = segmentation_mask[0].squeeze().cpu().numpy()
    character_mask_pil = Image.fromarray(((segmentation_mask!=0)*255).astype('uint8')).resize((512,512))
    character_mask_highlight_pil = segmentation_mask_visualization(args.font_path,segmentation_mask)
    caption_pil = make_caption_pil(args.font_path, captions)
    
    # save pred_img
    pred_image_list = []
    for image in sample_images.float():
        image = (image / 2 + 0.5).clamp(0, 1).unsqueeze(0)
        image = image.cpu().permute(0, 2, 3, 1).numpy()[0]
        image = Image.fromarray((image * 255).round().astype("uint8")).convert('RGB')
        pred_image_list.append(image)
        
    # os.makedirs(f'{args.output_dir}/{sub_output_dir}', exist_ok=True)
    
    # image_pil.save(os.path.join(args.output_dir, sub_output_dir, 'render_text_image.png'))
    # enhancer = ImageEnhance.Brightness(segmentation_mask_from_pillow)
    # im_brightness = enhancer.enhance(5)
    # im_brightness.save(os.path.join(args.output_dir, sub_output_dir, 'segmentation_mask_from_pillow.png'))

    # 之后得把这个函数返回的image返回了
    blank_pil = combine_image(args, sub_output_dir, pred_image_list, image_pil, character_mask_pil, character_mask_highlight_pil, caption_pil)
    return blank_pil


# if __name__ == "__main__":
#     import gradio as gr
#     demo = gr.Interface(main, "text", "image")
#     demo.launch()
    
    
import gradio as gr
    
with gr.Blocks() as demo:
    gr.Markdown("TextDiffuser.")
    with gr.Tab("Text-to-Image"):
        with gr.Row():
            with gr.Column(scale=1):
                prompt = gr.Textbox(label='Input your prompt here. Please enclose keywords with single quotes.')
                slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
                slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
                slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
                button = gr.Button("Generate")
            with gr.Column(scale=1):
                output = gr.Image()
        button.click(text_to_image, inputs=[prompt,slider_step,slider_batch,slider_seed], outputs=output)
        
    # with gr.Tab("Text-to-Image-with-Template"):
    #     with gr.Row():
    #         with gr.Column(scale=1):
    #             text_input = gr.Textbox(label='Input your prompt here.')
    #             template_image = gr.Image(label='Template image')
    #             slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
    #             slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
    #             slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
    #             button = gr.Button("Generate")
    #         with gr.Column(scale=1):
    #             output = gr.Image()
    #     button.click(flip_text, inputs=text_input, outputs=output)
        
    # with gr.Tab("Text-Inpainting"):
    #     with gr.Row():
    #         with gr.Column(scale=1):
    #             text_input = gr.Textbox(label='Input your prompt here.')
    #             with gr.Row():
    #                 orig_image = gr.Image(label='Original image')
    #                 mask_image = gr.Image(label='Mask image')
    #             slider_step = gr.Slider(minimum=1, maximum=1000, value=50, label="Sample Step", info="The sampling step for TextDiffuser ranging from [1,1000].")
    #             slider_batch = gr.Slider(minimum=1, maximum=4, value=2, label="Sample Size", info="Number of samples generated from TextDiffuser.")
    #             slider_seed = gr.Slider(minimum=1, maximum=10000, label="Seed", info="The random seed for sampling.", randomize=True)
    #             button = gr.Button("Generate")
    #         with gr.Column(scale=1):
    #             output = gr.Image()
    #     button.click(flip_text, inputs=text_input, outputs=output)

demo.launch()