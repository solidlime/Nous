# ペルソナ sandbox の初期状態。sandbox_manager が SANDBOX_IMAGE で docker run する。
# 素の ubuntu:24.04 だと python3 / git / curl すら無く、診断系（ss / ip / ping / nc）も全滅するので、
# 「壊れたときに使う道具」まで焼き込む（herta-sandbox-requirements.md §2）。
# node / npm は入れない。要る時にペルソナが自分で入れる。
#
# build: docker build -t ghcr.io/solidlime/nous-sandbox:latest docker/sandbox
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# tzdata は TZ（runtime で渡す）の解決に要る。TZ 自体は焼かない。
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git curl jq ripgrep build-essential pkg-config \
        less vim-tiny iproute2 iputils-ping dnsutils netcat-openbsd socat procps psmisc lsof \
        rsync unzip tree ca-certificates openssh-client tmux file xxd tzdata \
    && rm -rf /var/lib/apt/lists/*

# PEP 668: システム python に pip で入れられないので venv を既定にする。
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# git identity の既定。manager が SANDBOX_GIT_USER_NAME / _EMAIL を渡したときは
# GIT_AUTHOR_* / GIT_COMMITTER_* の env で上書きされる。
RUN git config --system user.name persona \
    && git config --system user.email persona@nous.local \
    && git config --system init.defaultBranch main

WORKDIR /home/agent

# 非 root で動かす。UID/GID はホスト（Synology は 1026/users）に合わせる。
# 合わせないと bind した workspace/wiki に書き込めず、ホスト側でも読めない
# 所有者のファイルができる。runner が --user でも渡すので、ここは
# イメージ単体で `docker run` した場合の既定。
ARG SANDBOX_UID=1026
ARG SANDBOX_GID=100
RUN groupadd -g ${SANDBOX_GID} agent \
    && useradd -u ${SANDBOX_UID} -g ${SANDBOX_GID} -m -d /home/agent -s /bin/bash agent
USER agent

CMD ["sleep", "infinity"]
