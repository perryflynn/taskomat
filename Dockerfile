FROM reg.git.brickburg.de/bbcontainers/hub/debian:bullseye-slim
WORKDIR /
SHELL [ "/bin/bash", "-c" ]

ENV DEBIAN_FRONTEND=noninteractive
ENV APTOPTS="--yes --no-install-recommends -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold"

ADD src /src

RUN apt update && \
    apt-get $APTOPTS upgrade && apt-get $APTOPTS dist-upgrade && \
    apt-get $APTOPTS install python3 python3-pip python3-wheel python3-setuptools jq && \
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

RUN chmod a+x /src/*.py && \
    pip3 install --no-cache-dir -r /src/requirements.txt

ENV TASKOMAT_LABEL_OBSOLETE="Workflow:Obsolete"
ENV TASKOMAT_LABEL_PUBLIC="Workflow:Public"
ENV TASKOMAT_LABEL_BACKLOG="Workflow:Backlog"
ENV TASKOMAT_LABEL_APPROVED="Workflow:Approved"
ENV TASKOMAT_LABEL_WIP="Workflow:Work in Progress"
ENV TASKOMAT_LABEL_HOLD="Workflow:On Hold"
ENV TASKOMAT_LABEL_TASKOMAT_COUNTER="TaskOMat:Counter"
