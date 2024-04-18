FROM ubuntu:latest

RUN mkdir /workdir /workdir/project
WORKDIR /workdir

RUN apt-get update \
 && apt-get install -y ghc wget unzip openjdk-11-jdk python3 python3-pip \
 && wget "https://github.com/viperproject/viper-ide/releases/download/v4.3.1/ViperToolsLinux.zip"  \
 && unzip "ViperToolsLinux.zip"

RUN pip3 install requests

COPY ./ /workdir
