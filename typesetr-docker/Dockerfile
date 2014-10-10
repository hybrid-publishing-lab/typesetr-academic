FROM ubuntu:12.04
MAINTAINER Johannes Amorosa <johannes.amorosa@gmail.com>

RUN echo "deb http://de.archive.ubuntu.com/ubuntu/ precise main universe" >> /etc/apt/sources.list
RUN apt-get -y update
RUN apt-get -y install curl wget unzip fontconfig fontconfig-config libfontconfig1 libfreetype6 ttf-dejavu-core libxslt-dev libjpeg8 

RUN echo "deb http://repo.consortium.io/apt/debian precise main" >> /etc/apt/sources.list
RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 2D959194
RUN apt-get -y update
RUN apt-get -y install typesetr-converter typesetr-fonts typesetr-styles #typesetr-texlive
RUN apt-get clean && rm -rf /var/lib/apt/lists/*
#RUN git init /opt/typesetr/styles/typesetr
#RUN cd /opt/typesetr/styles/typesetr
#RUN git remote add -f origin git@github.com:hybrid-publishing-lab/typeset-templates.git
#RUN git config core.sparsecheckout true
#RUN echo "typeset-templates/templates/" >> .git/info/sparse-checkout
#RUN git pull origin master

#RUN wget https://github.com/joewalnes/websocketd/releases/download/v0.2.9/websocketd-0.2.9-linux_amd64.zip
#RUN mkdir /websocketd
#RUN cd /websocketd
#RUN /usr/bin/unzip ../websocketd-0.2.9-linux_amd64.zip -d .

ENTRYPOINT ["/opt/typesetr/bin/gdoc-to"]
CMD ["--help"]

