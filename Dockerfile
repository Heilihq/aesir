FROM docker:latest

RUN apk add --update --no-cache --virtual .build-deps \
      python \
      py-pip \
      git \
      openssh \
  && \
    apk del --purge build-base \
  && \
    rm -rf /var/cache/apk/*

ADD requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

ADD aesir.py /aesir.py

RUN apk del --purge py-pip

CMD ["python", "/aesir.py"]