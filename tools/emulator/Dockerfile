FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install paho-mqtt==2.1.0
COPY nodes.py /srv/nodes.py
CMD ["python", "/srv/nodes.py"]
