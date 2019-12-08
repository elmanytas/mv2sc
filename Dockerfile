FROM ubuntu:18.04

RUN apt-get update; \ 
    apt-get -y install python3 python3-yaml python3-simplejson; \
    apt-get clean