# Use an official Python runtime as a parent image
FROM python:3.7.4-slim

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY ./requirements.txt /app

# Install any needed packages specified in requirements.txt
RUN apt-get install libjpeg-dev
RUN apt-get install zlib1g-dev


RUN pip install -r /app/requirements.txt
RUN pip install https://download.pytorch.org/whl/Pillow-9.3.0-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
RUN pip install https://download.pytorch.org/whl/cu113/torch-1.12.1%2Bcu113-cp38-cp38-linux_x86_64.whl

# Define environment variable
ENV NAME gradio

# The default gradio port is 7860
EXPOSE 7860

# Run main.py when the container launches
CMD ["python", "text-to-image-app.py"]
~                            
