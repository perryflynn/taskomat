FROM debian:buster-slim
WORKDIR /
SHELL [ "/bin/bash", "-c" ]

ENV DEBIAN_FRONTEND=noninteractive
ENV APTOPTS="--yes --no-install-recommends -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold"

ADD src /src

RUN apt update && \
    apt-get $APTOPTS upgrade && apt-get $APTOPTS dist-upgrade && \
    apt-get $APTOPTS install procps net-tools bsd-mailx dnsutils \
        iproute2 iputils-ping zip unzip git curl wget rsync openssl-client \
        python3 python3-pip python3-wheel python3-setuptools && \
    apt-get $APTOPTS install -f && \
    apt-get $APTOPTS --purge autoremove && \
    apt-get $APTOPTS clean && \
    rm -rf /usr/share/man/* && \
    rm -rf /usr/share/doc/* && \
    rm -f /var/lib/systemd/catalog/database && \
    rm -f /etc/apt/apt.conf.d/01autoremove-kernels && \
    rm -f /var/log/apt/history.log && \
    rm -f /var/log/apt/term.log && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install -r /src/requirements.txt
