FROM tiangolo/uvicorn-gunicorn:python3.10
ENV URL_TO_APPLICATION_GITHUB='https://github.com/lapig-ufg/tiles.git' \
    BRANCH='main' \
    TILES_ENV='development'

LABEL maintainer="Jario Matos da Rocha <jairo@jairomr.com.br>"

WORKDIR /app

RUN apt-get update && apt-get install --no-install-recommends -y curl build-essential git nano && \
    mkdir -p /app && cd /app && \
    git clone -b ${BRANCH} ${URL_TO_APPLICATION_GITHUB} && \
    cd tiles && \
    pip install --no-cache-dir -r requirements.txt


COPY ./start.sh /app/start.sh
RUN chmod +x /app/start.sh


CMD sh -c "/app/start.sh"
