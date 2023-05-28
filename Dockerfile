# Use an official Python runtime as a parent image
FROM python:3.7.4-slim

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip3 install --trusted-host pypi.python.org -r requirements.txt && pip3 install torch==1.13.1 --no-dependencies && pip3 install torchvision==0.2.1 --no-dependencies && git clone https://github.com/huggingface/diffusers && cp ./assets/files/scheduling_ddpm.py ./diffusers/src/diffusers/schedulers/scheduling_ddpm.py && cp ./assets/files/unet_2d_condition.py ./diffusers/src/diffusers/models/unet_2d_condition.py && cp ./assets/files/modeling_utils.py ./diffusers/src/diffusers/models/modeling_utils.py && cd diffusers && pip install -e .

# Define environment variable
ENV NAME gradio

# The default gradio port is 7860
EXPOSE 7860

# Run main.py when the container launches
CMD ["python", "app.py"]
~                            
